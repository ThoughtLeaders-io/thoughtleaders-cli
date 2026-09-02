#!/usr/bin/env python3
"""Render the two human surfaces of a creator brief from facts + meta.

Deterministic templating in code — the template lives here, is never
redesigned per run, and the model never hand-writes HTML. JSONL + Markdown
stay canonical; HTML is the view.

Usage:
    build_html.py --facts <channel_id>-facts.jsonl --meta <channel_id>-meta.json
        [--ledger-out <channel_id>-profile-ledger.html]
    build_html.py --in <channel_id>-<brand_id>-connections.md
        --facts <channel_id>-facts.jsonl --meta <channel_id>-meta.json
        [--out <channel_id>-<brand_id>-connections.html]

Two surfaces:

- the **ledger view** (PROFILE mode's human surface): the meta strip
  (build date, corpus window, coverage counts, format label), the tallies
  (confidence, sensitivity tier, domain) and every fact with its full
  citation and its tier. Written whenever ``--facts`` is given and no
  ``--in``; default path ``<facts dir>/<channel_id>-profile-ledger.html``.
- the **connections page** (CONNECT's deliverable): a "who they are"
  section rendered from the ledger at render time — the top recurring facts
  by life domain, the format label, the corpus window — above the ranked
  connection map the markdown carries. Provenance labels in the markdown
  (``[web]``, ``[social: …]``) are kept: a connection map names its lanes.

Facts at tier ``children`` or ``location`` never enter the who-they-are
section (they are withheld from brand-facing angles by default); ``clinical``
does, carrying its tier badge, per ``references/evidence-rules.md``.

Fonts load from Google Fonts with system fallbacks declared, so the page reads
the same offline; nothing else is fetched and there is no script.
"""
from __future__ import annotations

import argparse
import html
import json
import pathlib
import re
from collections import Counter, defaultdict

BADGES = {
    "direct": "direct",
    "adjacent": "adjacent",
    "category precedent": "precedent",
    "category-precedent": "precedent",
    "confirmed": "confirmed",
    "unconfirmed": "unconfirmed",
    "lifestyle": "lifestyle",
    "clinical": "clinical",
    "children": "withheld",
    "location": "withheld",
    "withheld": "withheld",
    "no fit": "nofit",
    "no-fit": "nofit",
}
TIER_ORDER = ("none", "lifestyle", "clinical", "children", "location")
WITHHELD = {"children", "location"}          # never on a brand-facing page by default
DOMAIN_LABELS = {
    "origin": "Origin", "family": "Family", "pets": "Pets", "home": "Home",
    "work": "Work", "money": "Money", "health": "Health", "habits": "Habits",
    "tastes": "Tastes", "beliefs": "Beliefs", "relationships": "Relationships",
    "other": "Other",
}
WHO_MAX_FACTS = 12
WHO_MAX_PER_DOMAIN = 3

FONTS = ("https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,500;9..144,600"
         "&family=Source+Sans+3:ital,wght@0,400;0,600;1,400&family=IBM+Plex+Mono:wght@400;500"
         "&display=swap")

CSS = """
:root {
  --bg: #f2f4f6; --surface: #ffffff; --ink: #172029; --ink-2: #4b5866;
  --ink-3: #79858f; --line: #d6dde4; --accent: #0b6f8f; --accent-soft: #dbeef4;
  --quote: #33404c;
  --badge-direct: #0b6f8f; --badge-adjacent: #6a4fc4; --badge-precedent: #8a6a12;
  --badge-confirmed: #1f7a5a; --badge-unconfirmed: #8c6a12;
  --badge-lifestyle: #1f7a5a; --badge-clinical: #a35a12; --badge-withheld: #9b2f2f;
  --badge-nofit: #5b6472;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --bg: #10161c; --surface: #171f28; --ink: #e4e9ed; --ink-2: #adb8c2;
    --ink-3: #7b8792; --line: #283442; --accent: #58bcd8; --accent-soft: #143241;
    --quote: #c2ccd6;
    --badge-direct: #3d9fbe; --badge-adjacent: #9a84e0; --badge-precedent: #c9a43a;
    --badge-confirmed: #45a37f; --badge-unconfirmed: #c9a43a;
    --badge-lifestyle: #45a37f; --badge-clinical: #d08a45; --badge-withheld: #d76b6b;
    --badge-nofit: #8b95a3;
  }
}
:root[data-theme="dark"] {
  --bg: #10161c; --surface: #171f28; --ink: #e4e9ed; --ink-2: #adb8c2;
  --ink-3: #7b8792; --line: #283442; --accent: #58bcd8; --accent-soft: #143241;
  --quote: #c2ccd6;
  --badge-direct: #3d9fbe; --badge-adjacent: #9a84e0; --badge-precedent: #c9a43a;
  --badge-confirmed: #45a37f; --badge-unconfirmed: #c9a43a;
  --badge-lifestyle: #45a37f; --badge-clinical: #d08a45; --badge-withheld: #d76b6b;
  --badge-nofit: #8b95a3;
}
* { box-sizing: border-box; }
body {
  margin: 0; background: var(--bg); color: var(--ink);
  font: 17px/1.6 "Source Sans 3", "Source Sans Pro", -apple-system,
        BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
}
main { max-width: 860px; margin: 0 auto; padding: 2.75rem 1.25rem 5rem; }
h1, h2, h3 {
  font-family: Fraunces, "Iowan Old Style", Georgia, "Times New Roman", serif;
  font-weight: 600; line-height: 1.15; text-wrap: balance; margin: 0;
}
h1 { font-size: 2.3rem; letter-spacing: -.01em; }
h2 { font-size: 1.45rem; margin: 2.8rem 0 1rem; }
h3 { font-size: 1.15rem; margin: 0; }
p { margin: .5rem 0; max-width: 68ch; }
a { color: var(--accent); text-decoration: none; }
a:hover, a:focus-visible { text-decoration: underline; }
a:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
ul, ol { margin: .5rem 0; padding-left: 1.3rem; }
li { margin: .3rem 0; }
hr { border: none; border-top: 1px solid var(--line); margin: 1.8rem 0; }
code {
  font-family: "IBM Plex Mono", ui-monospace, Menlo, Consolas, monospace;
  font-size: .85em; background: var(--accent-soft); border-radius: 3px;
  padding: .05rem .3rem;
}
blockquote {
  margin: .7rem 0; padding: .55rem 1rem; color: var(--quote);
  border-left: 3px solid var(--accent); font-style: italic;
  font-family: Fraunces, "Iowan Old Style", Georgia, serif; font-size: 1.05rem;
}
blockquote p { margin: .2rem 0; max-width: none; }
.eyebrow {
  font-family: "IBM Plex Mono", ui-monospace, Menlo, monospace;
  font-size: .72rem; letter-spacing: .12em; text-transform: uppercase;
  color: var(--ink-3); margin: 0 0 .6rem;
}
header { padding-bottom: 1.4rem; border-bottom: 1px solid var(--line); }
.meta {
  display: flex; flex-wrap: wrap; gap: .4rem .9rem; margin: .9rem 0 0;
  padding: 0; list-style: none; font-family: "IBM Plex Mono", ui-monospace, monospace;
  font-size: .76rem; color: var(--ink-2); font-variant-numeric: tabular-nums;
}
.meta li { margin: 0; }
.meta li::before { content: "·"; color: var(--ink-3); margin-right: .55rem; }
.meta li:first-child::before { content: none; margin: 0; }
.ledger {
  margin: 1.2rem 0 0; padding: .75rem 1rem; background: var(--surface);
  border: 1px solid var(--line); border-radius: 6px; font-size: .9rem;
  color: var(--ink-2);
}
.tally { display: flex; flex-wrap: wrap; gap: .3rem 1.2rem; margin: .2rem 0 0; padding: 0; list-style: none; }
.tally li { margin: 0; font-variant-numeric: tabular-nums; }
.who {
  display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
  gap: 1rem 1.6rem; margin: 0;
}
.who .domain { border-top: 2px solid var(--accent); padding-top: .5rem; }
.who .domain h3 {
  font-family: "IBM Plex Mono", ui-monospace, monospace; font-weight: 500;
  font-size: .74rem; letter-spacing: .1em; text-transform: uppercase;
  color: var(--ink-3); margin: 0 0 .35rem;
}
.who ul { list-style: none; margin: 0; padding: 0; }
.who li { margin: 0 0 .55rem; }
.who .claim { font-weight: 600; }
.who .q {
  display: block; color: var(--ink-2); font-size: .92rem; font-style: italic;
  font-family: Fraunces, "Iowan Old Style", Georgia, serif;
}
.who .q a { color: var(--ink-3); font-style: normal; font-family: "IBM Plex Mono", monospace; font-size: .72rem; }
.conn { list-style: none; margin: 0; padding: 0; counter-reset: rank; }
.conn > li {
  display: grid; grid-template-columns: 3rem 1fr; gap: 0 1rem; margin: 0 0 1.1rem;
  padding: 1rem 1.1rem 1.1rem .9rem; background: var(--surface);
  border: 1px solid var(--line); border-radius: 6px;
}
.conn > li::before {
  counter-increment: rank; content: counter(rank, decimal-leading-zero);
  font-family: Fraunces, Georgia, serif; font-size: 1.9rem; line-height: 1;
  color: var(--ink-3); font-variant-numeric: tabular-nums; padding-top: .1rem;
}
.conn .body { min-width: 0; }
.conn h3 { margin: 0 0 .4rem; }
.conn h3 .badge { margin-left: .5rem; vertical-align: .2em; }
.conn p { max-width: 70ch; }
.prose { margin-top: 1rem; }
.facts { margin: 1.4rem 0 0; padding: 0; list-style: none; }
.facts > li {
  margin: 0 0 .8rem; padding: .7rem 1rem .8rem; background: var(--surface);
  border: 1px solid var(--line); border-radius: 6px;
}
.facts .claim { font-weight: 600; margin: 0; }
.facts .claim .badge { margin-left: .5rem; vertical-align: .15em; }
.facts .src {
  margin: .35rem 0 0; font-family: "IBM Plex Mono", ui-monospace, monospace;
  font-size: .74rem; color: var(--ink-3); word-break: break-word; max-width: none;
}
.badge {
  display: inline-block; padding: .08rem .5rem; border-radius: 3px;
  font-family: "IBM Plex Mono", ui-monospace, monospace; font-size: .66rem;
  font-weight: 500; letter-spacing: .08em; text-transform: uppercase;
  font-style: normal; color: var(--surface); vertical-align: middle;
}
.badge-direct { background: var(--badge-direct); }
.badge-adjacent { background: var(--badge-adjacent); }
.badge-precedent { background: var(--badge-precedent); }
.badge-confirmed { background: var(--badge-confirmed); }
.badge-unconfirmed { background: var(--badge-unconfirmed); }
.badge-lifestyle { background: var(--badge-lifestyle); }
.badge-clinical { background: var(--badge-clinical); }
.badge-withheld { background: var(--badge-withheld); }
.badge-nofit { background: var(--badge-nofit); }
.empty { color: var(--ink-2); font-style: italic; }
.links { list-style: none; padding: 0; margin: 0; font-size: .92rem; color: var(--ink-2); }
.links li { margin: .3rem 0; word-break: break-word; }
.scroll { overflow-x: auto; }
@media (prefers-reduced-motion: no-preference) { a { transition: color .15s; } }
"""


# --------------------------------------------------------------------------- #
# markdown
# --------------------------------------------------------------------------- #
def parse_frontmatter(text: str) -> tuple[dict, str]:
    """Flat ``key: value`` frontmatter (the connections contract's shape)."""
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---", 4)
    if end < 0:
        return {}, text
    meta = {}
    for line in text[4:end].splitlines():
        m = re.match(r"^(\w[\w-]*):\s*(.*)$", line)
        if m:
            meta[m.group(1)] = m.group(2).strip().strip('"')
    return meta, text[end + 4:].lstrip("\n")


def badge(token: str) -> str | None:
    cls = BADGES.get(token.strip().lower())
    return f'<span class="badge badge-{cls}">{html.escape(token.strip())}</span>' if cls else None


def inline(text: str) -> str:
    """Escaped text -> inline HTML: links, bold (with badges), italic, code."""
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    # the surrounding escape pass already entity-escaped the URL once
    # (quote=False, so quotes survived): decode back to the raw URL, then
    # escape once for attribute context — a quote in a crafted link target
    # must not break out of href, and a & must not double-escape to &amp;amp;
    text = re.sub(
        r"\[([^\]]+)\]\((https?://[^)\s]+)\)",
        lambda m: ('<a href="'
                   f'{html.escape(html.unescape(m.group(2)), quote=True)}">'
                   f"{m.group(1)}</a>"),
        text)

    def bold(m: re.Match) -> str:
        return badge(m.group(1)) or f"<strong>{m.group(1)}</strong>"

    text = re.sub(r"\*\*([^*]+)\*\*", bold, text)
    text = re.sub(r"(?<!\w)\*([^*]+)\*(?!\w)", r"<em>\1</em>", text)
    return text


def render_markdown(md: str) -> str:
    out: list[str] = []
    in_list = None      # "ul" | "ol" | None
    in_quote = False
    para: list[str] = []

    def close_para() -> None:
        if para:
            out.append(f"<p>{inline(' '.join(para))}</p>")
            para.clear()

    def close_list() -> None:
        nonlocal in_list
        if in_list:
            out.append(f"</{in_list}>")
            in_list = None

    def close_quote() -> None:
        nonlocal in_quote
        if in_quote:
            out.append("</blockquote>")
            in_quote = False

    for raw in md.splitlines():
        line = html.escape(raw.rstrip(), quote=False)
        stripped = line.strip()
        if not stripped:
            close_para(), close_list(), close_quote()
            continue
        h = re.match(r"^(#{1,4})\s+(.*)$", stripped)
        if h:
            close_para(), close_list(), close_quote()
            n = len(h.group(1))
            out.append(f"<h{n}>{inline(h.group(2))}</h{n}>")
            continue
        if re.fullmatch(r"-{3,}|\*{3,}", stripped):
            close_para(), close_list(), close_quote()
            out.append("<hr>")
            continue
        if stripped.startswith("&gt;"):
            close_para(), close_list()
            if not in_quote:
                out.append("<blockquote>")
                in_quote = True
            out.append(f"<p>{inline(stripped[4:].strip())}</p>")
            continue
        close_quote()
        m = re.match(r"^[-*]\s+(.*)$", stripped)
        if m:
            close_para()
            if in_list != "ul":
                close_list()
                out.append("<ul>")
                in_list = "ul"
            out.append(f"<li>{inline(m.group(1))}</li>")
            continue
        m = re.match(r"^\d+\.\s+(.*)$", stripped)
        if m:
            close_para()
            if in_list != "ol":
                close_list()
                out.append("<ol>")
                in_list = "ol"
            out.append(f"<li>{inline(m.group(1))}</li>")
            continue
        close_list()
        para.append(stripped)
    close_para(), close_list(), close_quote()
    return "\n".join(out)


def connection_cards(body_html: str) -> str:
    """Each ``## …`` section of the connection map becomes one ranked card;
    whatever precedes the first section stays prose (the header lines, or a
    no-fit verdict). Sections are the ranking, so cards are numbered."""
    parts = re.split(r"(?=<h2>)", body_html)
    intro = parts[0].strip()
    cards = []
    for chunk in parts[1:]:
        m = re.match(r"<h2>(.*?)</h2>\n?(.*)", chunk, re.S)
        if not m:
            continue
        title, rest = m.group(1), m.group(2).strip()
        # a leading "1. " in the heading duplicates the card's own numeral
        title = re.sub(r"^\d+[.)]\s*", "", title)
        cards.append(f'<li><div class="body"><h3>{title}</h3>{rest}</div></li>')
    out = f'<div class="prose">{intro}</div>' if intro else ""
    if cards:
        out += f'<ol class="conn">{"".join(cards)}</ol>'
    return out


# --------------------------------------------------------------------------- #
# ledger data
# --------------------------------------------------------------------------- #
def load_facts(facts_path: pathlib.Path) -> list[dict]:
    facts: list[dict] = []
    with open(facts_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                facts.append(json.loads(line))
    return facts


def load_meta(meta_path: pathlib.Path | None) -> dict:
    if not meta_path:
        return {}
    return json.loads(pathlib.Path(meta_path).read_text(encoding="utf-8"))


def tier_of(fact: dict) -> str:
    tier = str(fact.get("sensitivity") or "").lower()
    if tier in TIER_ORDER:
        return tier
    # a ledger written against the old boolean: the flag alone cannot say
    # which withheld tier, so it renders as withheld without naming one
    return "withheld" if fact.get("sensitive") else "none"


def tier_badge(fact: dict) -> str:
    tier = tier_of(fact)
    if tier == "none":
        return ""
    label = tier if tier in TIER_ORDER else "withheld"
    return badge(label) or ""


def meta_chips(meta: dict) -> str:
    chips = []
    if meta.get("generated_at"):
        chips.append(f"built {meta['generated_at']}")
    window = meta.get("corpus_window")
    if isinstance(window, str):
        chips.append(f"corpus {window.strip('[]')}")
    elif isinstance(window, (list, tuple)) and any(window):
        lo, hi = (list(window) + [None, None])[:2]
        chips.append(f"corpus {lo or '?'} → {hi or '?'}")
    cov = meta.get("coverage") or {}
    if cov.get("videos_matched") and cov.get("videos_with_transcript"):
        chips.append(f"{cov['videos_matched']}/{cov['videos_with_transcript']} "
                     "transcript videos matched")
    if cov.get("windows_judged"):
        chips.append(f"{cov['windows_judged']} passages judged")
    if cov.get("facts"):
        chips.append(f"{cov['facts']} facts")
    if meta.get("format"):
        chips.append(f"format: {meta['format']}")
    if meta.get("lanes"):
        chips.append(f"lanes: {meta['lanes']}")
    if meta.get("rounds") and int(meta.get("rounds") or 1) > 1:
        chips.append(f"{meta['rounds']} rounds")
    if meta.get("brand_id"):
        chips.append(f"brand {meta['brand_id']}")
    if not chips:
        return ""
    items = "".join(f"<li>{html.escape(str(c))}</li>" for c in chips)
    return f'<ul class="meta">{items}</ul>'


def ledger_strip(facts: list[dict]) -> str:
    confidence: Counter = Counter()
    domains: Counter = Counter()
    tiers: Counter = Counter()
    for fact in facts:
        confidence[str(fact.get("confidence") or "unknown")] += 1
        domains[str(fact.get("domain") or "other")] += 1
        tiers[tier_of(fact)] += 1
    conf = ", ".join(f"{n} {k}" for k, n in confidence.most_common())
    doms = ", ".join(f"{k} {n}" for k, n in domains.most_common(6))
    tier_parts = [f"{tiers[t]} {t}" for t in TIER_ORDER[1:] if tiers[t]]
    if tiers["withheld"]:
        tier_parts.append(f"{tiers['withheld']} withheld (untiered)")
    # withheld from angles: children, location, untiered-but-flagged, and
    # clinical unless the creator made it public themselves — discussed in 3+
    # videos (evidence-rules.md); a story framing is a judgment the merge pass
    # records as recurrence, the renderer only counts
    withheld = (sum(tiers[t] for t in WITHHELD) + tiers["withheld"]
                + sum(1 for f in facts if tier_of(f) == "clinical"
                      and int(f.get("recurrence") or 0) < 3))
    tier_text = (", ".join(tier_parts) + (f" — {withheld} withheld from angles" if withheld else "")
                 if tier_parts else "all at tier none")
    items = "".join(f"<li>{html.escape(x)}</li>" for x in (
        f"{len(facts)} facts: {conf}",
        f"sensitivity: {tier_text}",
        f"domains: {doms}",
    ))
    return (f'<div class="ledger">Full ledger — every verified fact, with its citation.'
            f'<ul class="tally">{items}</ul></div>')


def ledger_facts(facts: list[dict]) -> str:
    """Every fact with its full citation and its sensitivity tier."""
    items = []
    for fact in facts:
        claim = html.escape(str(fact.get("claim") or ""))
        parts = [f'<p class="claim">{claim}{tier_badge(fact)}</p>']
        if fact.get("quote"):
            quote = html.escape(str(fact["quote"]))
            parts.append(f"<blockquote><p>{quote}</p></blockquote>")
        cite = []
        for key in ("provenance", "domain", "confidence", "video", "published",
                    "seen_date", "recurrence", "fact_id"):
            if fact.get(key) not in (None, ""):
                cite.append(f"{key}: {fact[key]}")
        cite.append(f"sensitivity: {tier_of(fact)}")
        if fact.get("superseded_by"):
            cite.append(f"superseded by {fact['superseded_by']}")
        if fact.get("selected"):
            cite.append("selected")
        line = html.escape(" · ".join(cite))
        for key in ("url", "source_url"):
            if fact.get(key):
                raw = str(fact[key])
                # ledger data is researched/hand-edited content: only
                # http(s) becomes a link, anything else renders as text
                if raw.lower().startswith(("http://", "https://")):
                    url = html.escape(raw, quote=True)
                    line += f' · <a href="{url}">{html.escape(raw)}</a>'
                else:
                    line += f" · {html.escape(raw)}"
        items.append(f'<li>{"".join(parts)}<p class="src">{line}</p></li>')
    if not items:
        return '<p class="empty">No verified facts in this ledger.</p>'
    return f'<ul class="facts">{"".join(items)}</ul>'


# --------------------------------------------------------------------------- #
# who they are (connections page)
# --------------------------------------------------------------------------- #
def pick_who(facts: list[dict], *, max_facts: int = WHO_MAX_FACTS,
             per_domain: int = WHO_MAX_PER_DOMAIN) -> list[tuple[str, list[dict]]]:
    """Top recurring facts by domain: selected first, then recurrence, then
    confirmed. Superseded facts and the withheld tiers never appear."""
    usable = [f for f in facts
              if not f.get("superseded_by") and tier_of(f) not in WITHHELD
              and tier_of(f) != "withheld"]

    def key(f: dict):
        return (bool(f.get("selected")), int(f.get("recurrence") or 0),
                f.get("confidence") == "confirmed")

    usable.sort(key=key, reverse=True)
    by_domain: dict[str, list[dict]] = defaultdict(list)
    total = 0
    for f in usable:
        d = str(f.get("domain") or "other")
        if len(by_domain[d]) >= per_domain:
            continue
        by_domain[d].append(f)
        total += 1
        if total >= max_facts:
            break
    # domains ordered by how much of the ledger they hold — what the creator
    # talks about most comes first
    weight = Counter(str(f.get("domain") or "other") for f in usable)
    return sorted(by_domain.items(), key=lambda kv: -weight[kv[0]])


def short_quote(quote: str, words: int = 14) -> str:
    toks = quote.split()
    return " ".join(toks[:words]) + ("…" if len(toks) > words else "")


def who_they_are(facts: list[dict], meta: dict) -> str:
    groups = pick_who(facts)
    fmt = meta.get("format")
    lead = []
    if fmt:
        lead.append(f"format: {fmt}")
    window = meta.get("corpus_window")
    if isinstance(window, (list, tuple)) and any(window):
        lo, hi = (list(window) + [None, None])[:2]
        lead.append(f"videos {str(lo or '?')[:7]} → {str(hi or '?')[:7]}")
    cov = meta.get("coverage") or {}
    if cov.get("facts"):
        lead.append(f"{cov['facts']} facts in the ledger")
    head = ('<h2>Who they are</h2>'
            + (f'<ul class="meta">{"".join(f"<li>{html.escape(x)}</li>" for x in lead)}</ul>'
               if lead else ""))
    if not groups:
        return head + '<p class="empty">The ledger holds no facts that can appear on a brand-facing page.</p>'
    cols = []
    for domain, items in groups:
        lis = []
        for f in items:
            claim = html.escape(str(f.get("claim") or ""))
            q = ""
            if f.get("quote"):
                q = html.escape(short_quote(str(f["quote"])))
                url = str(f.get("url") or "")
                if url.lower().startswith(("http://", "https://")):
                    q += f' <a href="{html.escape(url, quote=True)}">watch</a>'
                q = f'<span class="q">“{q}”</span>' if q else ""
            lis.append(f'<li><span class="claim">{claim}</span>{tier_badge(f)}{q}</li>')
        label = html.escape(DOMAIN_LABELS.get(domain, domain.title()))
        cols.append(f'<div class="domain"><h3>{label}</h3><ul>{"".join(lis)}</ul></div>')
    return head + f'<div class="who">{"".join(cols)}</div>'


# --------------------------------------------------------------------------- #
# page
# --------------------------------------------------------------------------- #
def page_html(title: str, eyebrow: str, header_extra: str, body: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title>
<link rel="stylesheet" href="{FONTS}">
<style>{CSS}</style>
</head>
<body>
<main>
<header>
<p class="eyebrow">{html.escape(eyebrow)}</p>
<h1>{html.escape(title)}</h1>
{header_extra}
</header>
{body}
</main>
</body>
</html>
"""


def context_section(meta: dict) -> str:
    """Linked platforms and sibling channels from the channel context — the
    parts of the old one-pager's "Other channels" section that still have no
    other home. Each platform says whether the socials lane read it."""
    ctx = meta.get("context") or {}
    links = ctx.get("social_links") or []
    sibs = ctx.get("second_channel_candidates") or []
    if not links and not sibs:
        return ""
    read = str(meta.get("lanes") or "") == "transcripts+socials"
    items = []
    for link in links:
        raw = str(link)
        shown = html.escape(raw)
        if raw.lower().startswith(("http://", "https://")):
            shown = f'<a href="{html.escape(raw, quote=True)}">{shown}</a>'
        items.append(f"<li>{shown} — {'read (socials lane)' if read else 'linked but unread (socials lane not run)'}</li>")
    for c in sibs:
        name = html.escape(str(c.get("name") or c.get("link") or ""))
        ident = c.get("id") or c.get("channel_id")
        tail = f" (id {html.escape(str(ident))})" if ident else ""
        items.append(f"<li>{name}{tail} — not mined</li>")
    return ('<h2>Other channels and platforms</h2>'
            f'<ul class="links">{"".join(items)}</ul>')


def render_ledger(facts: list[dict], meta: dict, title: str | None = None) -> str:
    name = title or meta.get("channel_name") or f"channel {meta.get('channel_id', '')}".strip()
    return page_html(f"{name} — ledger", "creator ledger",
                     meta_chips(meta) + "\n" + ledger_strip(facts),
                     ledger_facts(facts) + context_section(meta))


def render_connections(md_text: str, facts: list[dict] | None, meta: dict) -> tuple[str, str]:
    fm, body = parse_frontmatter(md_text)
    creator = fm.get("channel_name") or meta.get("channel_name") or "Creator"
    brand = fm.get("brand_name") or fm.get("brand_id") or "Brand"
    title = f"{creator} × {brand}"
    body_html = render_markdown(body)
    m = re.search(r"<h1>(.*?)</h1>", body_html)
    if m:
        # the markdown's own H1 replaces the derived title (decode: it was
        # entity-escaped once already and the template escapes again)
        title = html.unescape(re.sub(r"<[^>]+>", "", m.group(1)))
        body_html = body_html.replace(m.group(0), "", 1)
    chips = []
    if fm.get("brand_read_date"):
        chips.append(f"brand read {fm['brand_read_date']}")
    if fm.get("facts_file"):
        chips.append(f"from {fm['facts_file']}")
    header_extra = (f'<ul class="meta">{"".join(f"<li>{html.escape(c)}</li>" for c in chips)}</ul>'
                    if chips else "")
    who = who_they_are(facts, meta) if facts is not None else ""
    conn = "<h2>Connections</h2>" + connection_cards(body_html)
    return title, page_html(title, "creator × brand connection map", header_extra, who + conn)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="infile", default=None,
                    help="<channel_id>-<brand_id>-connections.md; omit for the ledger view")
    ap.add_argument("--facts", default=None, help="<channel_id>-facts.jsonl")
    ap.add_argument("--meta", default=None, help="<channel_id>-meta.json")
    ap.add_argument("--out", default=None,
                    help="connections page; default: input path with .html")
    ap.add_argument("--ledger-out", dest="ledger_out", default=None,
                    help="ledger view; default: <facts dir>/<channel_id>-profile-ledger.html")
    a = ap.parse_args()
    if not a.infile and not a.facts:
        ap.error("give --facts (ledger view) and/or --in (connections page)")

    facts = load_facts(pathlib.Path(a.facts)) if a.facts else None
    meta = load_meta(a.meta)
    result: dict = {}

    if a.infile:
        in_path = pathlib.Path(a.infile)
        out_path = pathlib.Path(a.out) if a.out else in_path.with_suffix(".html")
        title, page = render_connections(in_path.read_text(encoding="utf-8"), facts, meta)
        out_path.write_text(page, encoding="utf-8")
        result.update(html=str(out_path), title=title)
    elif facts is not None:
        facts_path = pathlib.Path(a.facts)
        stem = re.sub(r"-facts$", "", facts_path.stem)
        ledger_path = (pathlib.Path(a.ledger_out) if a.ledger_out
                       else facts_path.with_name(f"{stem}-profile-ledger.html"))
        ledger_path.write_text(render_ledger(facts, meta), encoding="utf-8")
        result.update(ledger_html=str(ledger_path))
    print(json.dumps(result))


if __name__ == "__main__":
    main()
