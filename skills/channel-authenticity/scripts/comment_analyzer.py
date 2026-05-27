#!/usr/bin/env python3
"""Group C — comment content analysis (the core of the skill).

Scrapes >=10 latest longforms (+ highest-view + most-recently-sponsored),
runs rule-based checks, and prepares a sampled batch for the Haiku
`youtube-comment-classifier` subagent (the orchestrator performs the actual
delegation via the Agent tool; this module just builds the batch and folds
the verdict back in).

Public:
  collect(channel, longform, shorts, focus_video) -> {video_id: [comments]}
  analyze(channel, scraped) -> {subscore, flags, metrics, llm_batch}
  apply_llm(result, classifications) -> updates result in place, returns it
"""
from __future__ import annotations

import re
import statistics
from collections import Counter

import comment_scraper

PENALTIES = {
    "C_comment_scarcity": (35, "critical"),
    "C_length_uniform": (12, "warning"),
    "C_language_mismatch": (20, "critical"),
    "C_generic_templates": (18, "warning"),
    "C_emoji_only": (10, "info"),
    "C_bot_usernames": (15, "warning"),
    "C_near_duplicates": (15, "warning"),
    "C_low_reply_ratio": (8, "info"),
    "C_no_creator_engagement": (6, "info"),
    "C_commenter_churn": (12, "warning"),
    "C_sentiment_uniform": (8, "info"),
    "C_llm_not_organic": (30, "critical"),
    "C_time_clustered": (8, "info"),
}

MIN_LONGFORMS = 10
LLM_SAMPLE = 60
# Auto-generated-handle share is only a red flag when the audience is
# independently suspect. At/above this organic share, YouTube's own default
# handles (letters+digits) dominate and the signal is noise — see analyze().
BOT_HANDLE_CORROBORATION_MAX_ORGANIC = 0.55

GENERIC = [
    "nice video", "great video", "great content", "thanks for sharing",
    "first", "love this", "love it", "keep it up", "keep going", "awesome",
    "amazing", "good job", "well done", "very nice", "so good", "best video",
    "informative", "helpful", "thank you so much", "wow", "super", "👍", "🔥",
    "❤", "great work", "nice one", "good video", "very helpful", "excellent",
]
EMOJI_RE = re.compile(
    "[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF←-⇿⌀-⏿]"
)
BOT_HANDLE_RE = re.compile(r"^@?[a-z]+[-_]?[0-9]{4,}$", re.I)
ASCII_LETTERS = re.compile(r"[A-Za-z]")


def collect(channel, longform, shorts, focus_video=None) -> dict[str, dict]:
    targets: list[dict] = list(longform[:MIN_LONGFORMS])
    seen = {v["video_id"] for v in targets}
    if longform:
        hv = max(longform, key=lambda v: v["views"])
        if hv["video_id"] not in seen:
            targets.append(hv)
            seen.add(hv["video_id"])
    if focus_video and focus_video.get("video_id") and focus_video["video_id"] not in seen:
        targets.append(focus_video)
    out: dict[str, dict] = {}
    for v in targets:
        cs = comment_scraper.scrape(v["video_id"], v.get("views", 0))
        out[v["video_id"]] = {"video": v, "comments": cs}
    return out


def _lang_is_ascii(text: str) -> bool:
    letters = ASCII_LETTERS.findall(text)
    total = [c for c in text if c.isalpha()]
    if not total:
        return True  # emoji/number-only handled elsewhere
    return len(letters) / len(total) >= 0.6


def analyze(channel: dict, scraped: dict[str, dict]) -> dict:
    flags, metrics = [], {}
    all_comments: list[dict] = []
    per_video_authors: list[set] = []
    for vid, blob in scraped.items():
        cs = blob["comments"]
        all_comments.extend(cs)
        per_video_authors.append({c["author"] for c in cs if c["author"]})

    viewer = [c for c in all_comments if not c["is_creator"]]
    metrics["videos_scraped"] = len(scraped)
    metrics["total_comments"] = len(all_comments)
    metrics["viewer_comments"] = len(viewer)
    metrics["videos_with_zero_viewer_comments"] = sum(
        1 for b in scraped.values()
        if not any(not c["is_creator"] for c in b["comments"])
    )

    # 0. comment scarcity vs scraped views — the single loudest signal.
    # A conservative organic floor is ~1 comment per 2,000 views (0.05%).
    # Real human audiences usually sit well above this; bot/promo traffic
    # produces almost none. Measured on ACTUALLY-SCRAPED comments so it can't
    # be explained away as a stale ES comment_count.
    scraped_views = sum(
        (b["video"].get("views") or 0) for b in scraped.values()
    )
    metrics["scraped_total_views"] = scraped_views
    if scraped_views >= 50_000:
        expected_floor = scraped_views / 2000.0
        ratio = len(viewer) / expected_floor if expected_floor else 1.0
        metrics["comment_to_expected_floor_ratio"] = ratio
        if ratio < 0.15:
            flags.append(_f("C_comment_scarcity",
                f"Only {len(viewer)} viewer comments across "
                f"{len(scraped)} videos totaling {scraped_views:,} views — "
                f"~{ratio*100:.0f}% of even a conservative organic floor "
                f"(1 per 2,000 views). A real audience this large leaves "
                f"orders of magnitude more comments."))

    if len(viewer) < 8:
        # Too few comments for the distribution sub-checks to be meaningful.
        # Scarcity (check 0) already carries the penalty; just stop here.
        if not any(f["code"] == "C_comment_scarcity" for f in flags):
            flags.append(_f("C_comment_scarcity",
                f"Only {len(viewer)} viewer comments across "
                f"{len(scraped)} videos — effectively a dead comment section "
                f"despite the view counts."))
        return _finalize(flags, metrics, viewer)

    texts = [c["text"] for c in viewer if c["text"]]

    # 1. length distribution
    wlens = [len(t.split()) for t in texts]
    short_share = sum(1 for n in wlens if n <= 5) / len(wlens) if wlens else 0
    med = statistics.median(wlens) if wlens else 0
    metrics["short_comment_share"] = short_share
    metrics["median_comment_words"] = med
    if short_share >= 0.7 and med < 8:
        flags.append(_f("C_length_uniform",
            f"{short_share*100:.0f}% of comments are <=5 words (median "
            f"{med:.0f}). Bot/padding comments cluster tight and short."))

    # 2. language match
    chan_lang = (channel.get("language") or "en").lower()
    if chan_lang == "en":
        match = sum(1 for t in texts if _lang_is_ascii(t)) / len(texts)
        metrics["language_match_share"] = match
        if match < 0.6:
            flags.append(_f("C_language_mismatch",
                f"Only {match*100:.0f}% of comments are in the channel's "
                f"language ({chan_lang}). Off-language comment farms are a "
                f"classic engagement-purchase tell."))

    # 3. generic templates
    gen = 0
    for t in texts:
        low = t.lower().strip(" .!?")
        if low in GENERIC or (len(low) <= 25 and any(g in low for g in GENERIC)):
            gen += 1
    gshare = gen / len(texts)
    metrics["generic_template_share"] = gshare
    if gshare > 0.4:
        flags.append(_f("C_generic_templates",
            f"{gshare*100:.0f}% of comments are generic template phrases "
            f"('nice video', emoji, etc.)."))

    # 4. emoji-only
    emo = 0
    for t in texts:
        stripped = EMOJI_RE.sub("", t)
        if len(t) and len(stripped.strip()) <= 2:
            emo += 1
    eshare = emo / len(texts)
    metrics["emoji_only_share"] = eshare
    if eshare > 0.25:
        flags.append(_f("C_emoji_only",
            f"{eshare*100:.0f}% of comments are emoji-only / no real text."))

    # 5. bot usernames — share computed here, but the FLAG is deferred to
    # apply_llm(): YouTube's own default handles are letters+digits too, so a
    # high share is only a red flag when the audience is independently suspect
    # (low organic share). Firing on format alone false-positives large/legacy
    # channels (The Infographics Show: 30% auto-handles, yet 80% organic).
    authors = [c["author"] for c in viewer if c["author"]]
    bot = sum(1 for a in authors if BOT_HANDLE_RE.match(a.lstrip("@")))
    bshare = bot / len(authors) if authors else 0
    metrics["bot_username_share"] = bshare

    # 6. near-duplicates (token Jaccard)
    dup = _largest_dup_cluster(texts)
    metrics["largest_dup_cluster_share"] = dup
    if dup > 0.10:
        flags.append(_f("C_near_duplicates",
            f"Largest near-duplicate comment cluster covers {dup*100:.0f}% "
            f"of comments — templated posting."))

    # 7. reply ratio — only meaningful if the scrape actually surfaced reply
    # data (yt-dlp doesn't always populate reply_count / pull child threads).
    # If we observed zero replies anywhere, treat reply data as unavailable
    # and skip rather than false-flag every channel.
    top = [c for c in viewer if not c["is_reply"]]
    observed_replies = sum(1 for c in all_comments if c["is_reply"]) + sum(
        c["replies"] for c in viewer if c["replies"] > 0
    )
    with_replies = sum(1 for c in top if c["replies"] > 0)
    rr = with_replies / len(top) if top else 0
    metrics["reply_ratio"] = rr
    metrics["reply_data_available"] = observed_replies > 0
    if top and observed_replies > 0 and rr < 0.05:
        flags.append(_f("C_low_reply_ratio",
            f"Only {rr*100:.0f}% of top comments have any reply — real "
            f"audiences converse far more."))

    # 8. creator engagement
    creator_touch = sum(1 for c in viewer if c["hearted"])
    ctr = creator_touch / len(viewer) if viewer else 0
    metrics["creator_heart_ratio"] = ctr
    if ctr == 0:
        flags.append(_f("C_no_creator_engagement",
            "Creator hearts/engages with zero comments — consistent with a "
            "comment section the creator knows isn't a real audience."))

    # 9. cross-video commenter overlap
    nonempty = [s for s in per_video_authors if s]
    if len(nonempty) >= 3:
        union = set().union(*nonempty)
        repeat = sum(1 for a in union if sum(a in s for s in nonempty) >= 2)
        overlap = repeat / len(union) if union else 0
        metrics["repeat_commenter_share"] = overlap
        if overlap < 0.02:
            flags.append(_f("C_commenter_churn",
                f"Only {overlap*100:.1f}% of commenters appear on >1 video — "
                f"no recurring real fanbase, pattern of throwaway accounts."))

    # 12. time clustering
    times = sorted(c["time"] for c in viewer if isinstance(c.get("time"), (int, float)))
    if len(times) >= 20:
        span = times[-1] - times[0]
        if span > 0:
            first_hr = sum(1 for t in times if t - times[0] <= 3600) / len(times)
            metrics["first_hour_comment_share"] = first_hr
            if first_hr > 0.5 and span > 7 * 86400:
                flags.append(_f("C_time_clustered",
                    f"{first_hr*100:.0f}% of comments landed in the first "
                    f"hour despite the video being weeks old — burst posting."))

    return _finalize(flags, metrics, viewer)


def _finalize(flags, metrics, viewer) -> dict:
    subscore = 100
    for f in flags:
        subscore -= f["penalty"]
    # llm batch: spread across videos, viewer comments only
    sample = [
        {"i": i, "text": c["text"][:280], "author": c["author"]}
        for i, c in enumerate(viewer)
        if c["text"]
    ][:LLM_SAMPLE]
    return {
        "subscore": max(subscore, 0),
        "flags": flags,
        "metrics": metrics,
        "llm_batch": sample,
    }


def merge_passes(passes: list[list[dict]]) -> tuple[list[str], list[float]]:
    """Majority-vote merge across N classifier passes for run-to-run
    stability. A comment is counted organic only if ≥half the passes called
    it organic (skeptical tie-break — organic must earn it). Returns the
    merged per-comment label list and the per-pass organic shares."""
    by_i: dict[int, list[str]] = {}
    per_pass_share: list[float] = []
    for p in passes:
        if not p:
            continue
        labs = [c.get("label", "") for c in p]
        per_pass_share.append(
            sum(1 for l in labs if l == "organic") / len(labs) if labs else 0.0
        )
        for c in p:
            by_i.setdefault(int(c.get("i", -1)), []).append(c.get("label", ""))
    merged: list[str] = []
    for i in sorted(by_i):
        votes = by_i[i]
        organic_votes = sum(1 for v in votes if v == "organic")
        if organic_votes * 2 >= len(votes) and organic_votes > 0:
            merged.append("organic")
        else:
            non_org = [v for v in votes if v != "organic"] or votes
            merged.append(Counter(non_org).most_common(1)[0][0])
    return merged, per_pass_share


def apply_llm(result: dict, classifications) -> dict:
    """`classifications` is either a single pass ``[{i,label}]`` or a list
    of passes ``[[{i,label}...], ...]``. Multiple passes are majority-voted
    for a stable organic share (the verdict is robust either way; this just
    stabilizes the reported number)."""
    if not classifications:
        result["metrics"]["llm_organic_share"] = None
        return result
    passes = classifications if classifications and isinstance(
        classifications[0], list
    ) else [classifications]

    labels, per_pass = merge_passes(passes)
    if not labels:
        result["metrics"]["llm_organic_share"] = None
        return result
    organic = sum(1 for l in labels if l == "organic")
    share = organic / len(labels)
    result["metrics"]["llm_organic_share"] = share
    result["metrics"]["llm_label_breakdown"] = dict(Counter(labels))
    result["metrics"]["llm_passes"] = len(passes)
    result["metrics"]["llm_per_pass_organic_share"] = [round(s, 3) for s in per_pass]
    if share < 0.5:
        result["flags"].append(_f("C_llm_not_organic",
            f"Haiku classifier ({len(passes)} pass(es), majority vote) judged "
            f"only {share*100:.0f}% of sampled comments organic "
            f"({dict(Counter(labels))})."))
        result["subscore"] = max(result["subscore"] - PENALTIES["C_llm_not_organic"][0], 0)
    # auto-generated-handle share corroborates padding only when the audience
    # is already suspect (see analyze() note). On a healthy-organic channel
    # those are just YouTube default handles — must not fire.
    bshare = result["metrics"].get("bot_username_share") or 0
    if bshare > 0.3 and share < BOT_HANDLE_CORROBORATION_MAX_ORGANIC:
        result["flags"].append(_f("C_bot_usernames",
            f"{bshare*100:.0f}% of commenter handles match auto-generated "
            f"patterns (letters+digits) alongside a low {share*100:.0f}% "
            f"organic share — corroborating padding."))
        result["subscore"] = max(
            result["subscore"] - PENALTIES["C_bot_usernames"][0], 0
        )
    result["hard_fail"] = share < 0.30
    return result


def _f(code: str, detail: str) -> dict:
    pen, sev = PENALTIES[code]
    return {"code": code, "severity": sev, "detail": detail, "penalty": pen}


def _largest_dup_cluster(texts: list[str]) -> float:
    norm = [set(re.findall(r"[a-z0-9]+", t.lower())) for t in texts]
    n = len(norm)
    if n < 5:
        return 0.0
    used = [False] * n
    best = 0
    for i in range(n):
        if used[i] or not norm[i]:
            continue
        cluster = 1
        for j in range(i + 1, n):
            if used[j] or not norm[j]:
                continue
            inter = len(norm[i] & norm[j])
            uni = len(norm[i] | norm[j]) or 1
            if inter / uni > 0.7:
                cluster += 1
                used[j] = True
        best = max(best, cluster)
    return best / n


if __name__ == "__main__":
    import json
    import sys

    import resolve_channel

    d = resolve_channel.resolve(sys.argv[1])
    sc = collect(d["channel"], d["longform"], d["shorts"], d.get("focus_video"))
    res = analyze(d["channel"], sc)
    print("subscore", res["subscore"], "(pre-LLM)")
    for f in res["flags"]:
        print(f["code"], f["severity"], "-", f["detail"])
    print("llm_batch size", len(res["llm_batch"]))
    print(json.dumps(res["metrics"], indent=2, default=str))
