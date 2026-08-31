#!/usr/bin/env python3
"""Render a profile or connections markdown file to self-contained HTML.

Deterministic templating in code — the template lives here, is never
redesigned per run, and the model never hand-writes HTML. Markdown + JSONL
stay canonical; the HTML is the human view: clean readable typography, one
accent color, facts and connections as a tidy list with styled quotes, small
badges for connection types (DIRECT / ADJACENT / CATEGORY PRECEDENT) and
confidence buckets, light + dark support, no JS, no external assets.

Usage:
    build_html.py --in <channel_id>-profile.md \\
        [--facts <channel_id>-facts.jsonl] [--out <channel_id>-profile.html]
    build_html.py --in <channel_id>-<brand_id>-connections.md

Two surfaces, deliberately separate:

- the **human page** (``--out``) carries the creator name, the headline and
  the facts — no generation date, corpus stats, video counts, format label,
  ledger tallies, or citation/source names. It is the page a person forwards.
- the **machine ledger view** (``--ledger-out``, written whenever ``--facts``
  is given, default ``<out>-ledger.html``) carries all of that verbatim: the
  meta chips, the ledger strip, and every fact with its full citation.

``--out`` defaults to the input path with ``.html``.
"""
from __future__ import annotations

import argparse
import html
import json
import pathlib
import re
from collections import Counter

BADGES = {
    "direct": "direct",
    "adjacent": "adjacent",
    "category precedent": "precedent",
    "category-precedent": "precedent",
    "confirmed": "confirmed",
    "unconfirmed": "unconfirmed",
    "sensitive": "sensitive",
}

CSS = """
:root {
  --bg: #ffffff; --fg: #1a1f2b; --muted: #5b6472; --accent: #0f6fde;
  --line: #e3e7ee; --card: #f6f8fb; --quote: #40495a;
  --badge-direct: #0f6fde; --badge-adjacent: #8a63d2;
  --badge-precedent: #b8860b; --badge-confirmed: #1a7f4b;
  --badge-unconfirmed: #9a6700; --badge-sensitive: #c0392b;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #14171d; --fg: #e6e9ef; --muted: #9aa3b2; --accent: #5aa2f0;
    --line: #2a3140; --card: #1b2029; --quote: #b9c2d0;
    --badge-direct: #5aa2f0; --badge-adjacent: #b39ddb;
    --badge-precedent: #d4a72c; --badge-confirmed: #4caf7d;
    --badge-unconfirmed: #d29922; --badge-sensitive: #e57368;
  }
}
* { box-sizing: border-box; }
body {
  margin: 0; background: var(--bg); color: var(--fg);
  font: 16px/1.65 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto,
        Helvetica, Arial, sans-serif;
}
main { max-width: 760px; margin: 0 auto; padding: 2.5rem 1.25rem 4rem; }
h1 { font-size: 1.7rem; line-height: 1.25; margin: 0 0 .4rem; }
h2 {
  font-size: 1.15rem; margin: 2.2rem 0 .7rem; padding-bottom: .3rem;
  border-bottom: 1px solid var(--line);
}
h3 { font-size: 1rem; margin: 1.5rem 0 .4rem; }
p { margin: .55rem 0; }
a { color: var(--accent); text-decoration: none; }
a:hover { text-decoration: underline; }
ul, ol { margin: .55rem 0; padding-left: 1.4rem; }
li { margin: .35rem 0; }
hr { border: none; border-top: 1px solid var(--line); margin: 1.8rem 0; }
code {
  background: var(--card); border: 1px solid var(--line);
  border-radius: 4px; padding: .05rem .35rem; font-size: .85em;
}
blockquote {
  margin: .8rem 0; padding: .6rem .95rem; color: var(--quote);
  background: var(--card); border-left: 3px solid var(--accent);
  border-radius: 0 6px 6px 0; font-style: italic;
}
blockquote p { margin: .25rem 0; }
.meta {
  display: flex; flex-wrap: wrap; gap: .4rem; margin: .8rem 0 0;
  padding: 0; list-style: none;
}
.meta li {
  margin: 0; padding: .15rem .6rem; border: 1px solid var(--line);
  border-radius: 999px; font-size: .8rem; color: var(--muted);
  background: var(--card);
}
.ledger {
  margin: 1.2rem 0 0; padding: .7rem .95rem; background: var(--card);
  border: 1px solid var(--line); border-radius: 8px; font-size: .88rem;
  color: var(--muted);
}
.facts { margin: 1.4rem 0 0; padding: 0; list-style: none; }
.facts > li {
  margin: 0 0 .9rem; padding: .7rem .95rem; background: var(--card);
  border: 1px solid var(--line); border-radius: 8px;
}
.facts .claim { font-weight: 600; }
.facts .src {
  margin: .3rem 0 0; font-size: .82rem; color: var(--muted);
  word-break: break-word;
}
.badge {
  display: inline-block; padding: .05rem .5rem; border-radius: 999px;
  font-size: .72rem; font-weight: 600; letter-spacing: .04em;
  text-transform: uppercase; font-style: normal;
  color: var(--bg); vertical-align: middle;
}
.badge-direct { background: var(--badge-direct); }
.badge-adjacent { background: var(--badge-adjacent); }
.badge-precedent { background: var(--badge-precedent); }
.badge-confirmed { background: var(--badge-confirmed); }
.badge-unconfirmed { background: var(--badge-unconfirmed); }
.badge-sensitive { background: var(--badge-sensitive); }
header { border-bottom: 2px solid var(--accent); padding-bottom: 1.1rem; }
"""


def parse_frontmatter(text: str) -> tuple[dict, str]:
    """Flat ``key: value`` frontmatter (the profile contract's shape)."""
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
        token = m.group(1)
        cls = BADGES.get(token.strip().lower())
        if cls:
            return f'<span class="badge badge-{cls}">{token}</span>'
        return f"<strong>{token}</strong>"

    text = re.sub(r"\*\*([^*]+)\*\*", bold, text)
    text = re.sub(r"(?<!\w)\*([^*]+)\*(?!\w)", r"<em>\1</em>", text)
    return text


# labelled forms ("source: X"); the bare form drops the ambiguous words
# ("per week", "via train" are ordinary prose, not citations)
_SOURCE_LABEL = r"(?:sources?|src|citations?|cites?|via|per|credit(?:ed to)?)"
_SOURCE_BARE = r"(?:sources?|src|citations?|cites?|credited to)"
# Source/citation annotations arrive as *content* from the research lanes, so
# they are stripped structurally (by the shape the spec mandates) and never by
# blocklisting names. The ledger view keeps every one of them.
SOURCE_PATTERNS = (
    # "(source: Famous Birthdays)", "[src: channel about page]"
    re.compile(rf"\s*[(\[]\s*{_SOURCE_LABEL}\s*[:=]\s*[^)\]]*[)\]]", re.I),
    # "(source Famous Birthdays)" — labelled words only; bare "via"/"per"
    # would eat ordinary prose ("(via train)"), so they need the ":" form
    re.compile(rf"\s*[(\[]\s*{_SOURCE_BARE}\s+[^)\]]*[)\]]", re.I),
    # provenance tags: "[web]", "[social: instagram]", "[transcript]"
    re.compile(r"\s*\[\s*(?:web|social|transcript)\s*(?::[^\]]*)?\]", re.I),
    # trailing "— source: X" running to end of line
    re.compile(rf"\s*(?:[—–]|--?|,|;)\s*{_SOURCE_LABEL}\s*[:=][^\n]*$",
               re.I),
)


def strip_sources(md: str) -> str:
    """Drop citation/source annotations from the human page's markdown.

    Structural: it removes the annotation *shapes* the profile spec defines
    (bracketed ``source:``/``via`` notes and provenance tags), never a list
    of known source names. A line left with nothing but its list marker is
    dropped whole.
    """
    out: list[str] = []
    for line in md.splitlines():
        if re.fullmatch(r"\s*(?:-{3,}|\*{3,})\s*", line):
            out.append(line)
            continue
        new = line
        for pat in SOURCE_PATTERNS:
            new = pat.sub("", new)
        if new != line:
            new = re.sub(r"(?<=\S)[ \t]{2,}(?=\S)", " ", new).rstrip()
            new = re.sub(r"[ \t]*[—–,;]+\s*$", "", new)
            if not new.strip(" \t-*>"):
                continue
        out.append(new)
    return "\n".join(out)


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


def meta_chips(meta: dict) -> str:
    chips = []
    if meta.get("generated_at"):
        chips.append(f"generated {meta['generated_at']}")
    if meta.get("corpus_window"):
        chips.append(f"corpus {meta['corpus_window'].strip('[]')}")
    if meta.get("videos_with_transcript") and meta.get("videos_total"):
        chips.append(f"{meta['videos_with_transcript']}/"
                     f"{meta['videos_total']} videos with transcript")
    if meta.get("format"):
        chips.append(f"format: {meta['format']}")
    if meta.get("brand_id"):
        chips.append(f"brand {meta['brand_id']}")
    if not chips:
        return ""
    items = "".join(f"<li>{html.escape(c)}</li>" for c in chips)
    return f'<ul class="meta">{items}</ul>'


def load_facts(facts_path: pathlib.Path) -> list[dict]:
    facts: list[dict] = []
    with open(facts_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                facts.append(json.loads(line))
    return facts


def ledger_strip(facts: list[dict]) -> str:
    confidence: Counter = Counter()
    domains: Counter = Counter()
    sensitive = 0
    total = len(facts)
    for fact in facts:
        confidence[str(fact.get("confidence") or "unknown")] += 1
        domains[str(fact.get("domain") or "other")] += 1
        if fact.get("sensitive"):
            sensitive += 1
    conf = ", ".join(f"{n} {k}" for k, n in confidence.most_common())
    doms = ", ".join(f"{k} {n}" for k, n in domains.most_common(6))
    text = (f"Full ledger: {total} facts ({conf}; {sensitive} sensitive) — "
            f"top domains: {doms}. The one-pager shows the strongest; this "
            f"ledger is the complete record.")
    return f'<div class="ledger">{html.escape(text)}</div>'


def ledger_facts(facts: list[dict]) -> str:
    """Every fact with its full citation — the ledger view only."""
    items = []
    for fact in facts:
        claim = html.escape(str(fact.get("claim") or ""))
        parts = [f'<p class="claim">{claim}</p>']
        if fact.get("quote"):
            quote = html.escape(str(fact["quote"]))
            parts.append(f"<blockquote><p>{quote}</p></blockquote>")
        cite = []
        for key in ("provenance", "domain", "confidence", "video", "published",
                    "seen_date", "recurrence", "fact_id"):
            if fact.get(key) not in (None, ""):
                cite.append(f"{key}: {fact[key]}")
        if fact.get("sensitive"):
            cite.append("sensitive")
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
        return ""
    return f'<ul class="facts">{"".join(items)}</ul>'


def page_html(title: str, header_extra: str, body: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title>
<style>{CSS}</style>
</head>
<body>
<main>
<header>
<h1>{html.escape(title)}</h1>
{header_extra}
</header>
{body}
</main>
</body>
</html>
"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="infile", required=True,
                    help="profile or connections markdown file")
    ap.add_argument("--facts", default=None,
                    help="<channel_id>-facts.jsonl: also writes the ledger "
                         "view (meta, tallies, full citations)")
    ap.add_argument("--out", default=None,
                    help="default: input path with .html")
    ap.add_argument("--ledger-out", dest="ledger_out", default=None,
                    help="ledger view path; default: <out stem>-ledger.html")
    a = ap.parse_args()

    in_path = pathlib.Path(a.infile)
    out_path = pathlib.Path(a.out) if a.out else in_path.with_suffix(".html")
    meta, body = parse_frontmatter(in_path.read_text(encoding="utf-8"))

    title = meta.get("channel_name") or in_path.stem
    if meta.get("brand_name"):
        title = f"{title} × {meta['brand_name']}"
    # Only the PROFILE one-pager is stripped: connection maps (brand_name in
    # the frontmatter) must keep their [web]/[social: …] provenance labels.
    body_html = render_markdown(body if meta.get("brand_name")
                                else strip_sources(body))
    # the markdown's own H1 (if any) replaces the derived title
    m = re.search(r"<h1>(.*?)</h1>", body_html)
    if m:
        # the rendered H1 is already entity-escaped; decode before the
        # template escapes the title once more
        title = html.unescape(re.sub(r"<[^>]+>", "", m.group(1)))
        body_html = body_html.replace(m.group(0), "", 1)

    # the human page: name, headline, facts. No methodology, no tallies,
    # no source names — all of that lives in the ledger view below.
    out_path.write_text(page_html(title, "", body_html), encoding="utf-8")
    result = {"html": str(out_path), "title": title}

    if a.facts:
        facts = load_facts(pathlib.Path(a.facts))
        ledger_path = (pathlib.Path(a.ledger_out) if a.ledger_out
                       else out_path.with_name(f"{out_path.stem}-ledger.html"))
        ledger_path.write_text(
            page_html(f"{title} — ledger",
                      meta_chips(meta) + "\n" + ledger_strip(facts),
                      ledger_facts(facts)),
            encoding="utf-8")
        result["ledger_html"] = str(ledger_path)

    print(json.dumps(result))


if __name__ == "__main__":
    main()
