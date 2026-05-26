#!/usr/bin/env python3
"""Scrape YouTube comments — SORTED BY RECENT, not popular.

Popular sort surfaces only the comments that earned engagement (the genuine
ones) and hides exactly the zero-engagement filler that bot/padding comments
produce — which is what we're hunting. So we always pull `new`/recent.

Backend: **yt-dlp with the `android` InnerTube player client**. This is the
key to a cookie-free / no-API-key / no-"are you a bot" path: the android
client is not subject to YouTube's web bot-check, so comments come back
without any authentication. youtube-comment-downloader is kept only as a
last-resort fallback (it breaks whenever YouTube changes its web API).

Per-video dynamic limit by view count: >=100k -> 1000, >=20k -> 500, else 300.
Needs no TL data — hits YouTube directly, works for anyone regardless of plan.

Normalized comment shape:
  {cid, text, author, votes, replies, time, is_reply, is_creator, hearted}
"""
from __future__ import annotations

import sys


def limit_for_views(views: int) -> int:
    if views >= 100_000:
        return 1000
    if views >= 20_000:
        return 500
    return 300


# --------------------------------------------------------------------------- #
# Primary: yt-dlp
# --------------------------------------------------------------------------- #
def _scrape_ytdlp(video_id: str, cap: int) -> list[dict]:
    import yt_dlp

    opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "getcomments": True,
        "check_formats": False,
        "extractor_args": {
            "youtube": {
                # android InnerTube client skips the web bot-check → no cookies
                "player_client": ["android"],
                "comment_sort": ["new"],          # RECENT, not top
                "max_comments": [str(cap), "all", "0", "all"],
            }
        },
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(
            f"https://www.youtube.com/watch?v={video_id}", download=False
        )
    raw = info.get("comments") or []
    out: list[dict] = []
    for c in raw:
        out.append(
            {
                "cid": c.get("id"),
                "text": (c.get("text") or "").strip(),
                "author": c.get("author") or "",
                "votes": int(c.get("like_count") or 0),
                "replies": int(c.get("reply_count") or 0),
                "time": c.get("timestamp"),
                "is_reply": (c.get("parent") not in (None, "root")),
                "is_creator": bool(c.get("author_is_uploader")),
                "hearted": bool(c.get("is_favorited")),
            }
        )
        if len(out) >= cap:
            break
    return out


# --------------------------------------------------------------------------- #
# Fallback: youtube-comment-downloader
# --------------------------------------------------------------------------- #
def _scrape_ycd(video_id: str, cap: int) -> list[dict]:
    from youtube_comment_downloader import SORT_BY_RECENT, YoutubeCommentDownloader

    dl = YoutubeCommentDownloader()
    out: list[dict] = []
    for c in dl.get_comments_from_url(
        f"https://www.youtube.com/watch?v={video_id}", sort_by=SORT_BY_RECENT
    ):
        out.append(
            {
                "cid": c.get("cid"),
                "text": (c.get("text") or "").strip(),
                "author": c.get("author") or "",
                "votes": _to_int(c.get("votes")),
                "replies": _to_int(c.get("replies")),
                "time": c.get("time"),
                "is_reply": bool(c.get("reply")),
                "is_creator": False,
                "hearted": bool(c.get("heart")),
            }
        )
        if len(out) >= cap:
            break
    return out


def _to_int(v) -> int:
    if v is None:
        return 0
    s = str(v).strip().upper().replace(",", "")
    try:
        if s.endswith("K"):
            return int(float(s[:-1]) * 1_000)
        if s.endswith("M"):
            return int(float(s[:-1]) * 1_000_000)
        return int(float(s))
    except ValueError:
        return 0


def scrape(video_id: str, views: int = 0, *, hard_cap: int | None = None) -> list[dict]:
    cap = hard_cap or limit_for_views(views)
    errors = []
    for name, fn in (("yt-dlp", _scrape_ytdlp), ("ycd", _scrape_ycd)):
        try:
            res = fn(video_id, cap)
            if res:
                return res
            errors.append(f"{name}: 0 comments")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{name}: {exc}")
            sys.stderr.write(f"[comment_scraper] {video_id} {name} failed: {exc}\n")
    sys.stderr.write(f"[comment_scraper] {video_id}: no comments ({'; '.join(errors)})\n")
    return []


if __name__ == "__main__":
    vid = sys.argv[1]
    cap = int(sys.argv[2]) if len(sys.argv) > 2 else 50
    cs = scrape(vid, hard_cap=cap)
    print(f"{len(cs)} comments (sorted recent)")
    for c in cs[:10]:
        tag = " [CREATOR]" if c["is_creator"] else (" [reply]" if c["is_reply"] else "")
        print(f"  [{c['author']}]{tag} {c['text'][:80]!r} votes={c['votes']}")
