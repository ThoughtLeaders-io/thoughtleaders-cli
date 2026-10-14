#!/usr/bin/env python3
"""Render the connections page, the core deliverable of a brand-creator connection run.

Deterministic templating in code, the template lives here, is never
redesigned per run, and the model never hand-writes HTML. The ledger
(``<channel_id>-facts.jsonl``, header + one fact per line) and the connection
map's markdown stay canonical; HTML is the view.

Usage:
    build_html.py --in .corpus/<id>/connections-<brand>.md \\
        --facts tl-creator-profiles/<id>-facts.jsonl \\
        [--out tl-creator-profiles/<id>-<brand>-connections.html]

``--out`` defaults to ``<facts dir>/<channel_id>-<brand_id>-connections.html``
when ``--facts`` is given (the markdown is a working file under
``.corpus/``; only the HTML lands in the deliverable directory), and to the
input path with an ``.html`` suffix when it is not. ``--meta`` is a legacy
escape hatch: the meta record is the ledger's first line, and the flag is
read only when the ledger carries no header.

The page is written for the brand: to judge the fit, or to pitch with. In
order:

- the header: creator × brand, with the date the map was prepared;
- **the verdict panel**: the label the markdown's ``## Verdict`` opens with
  (Strong fit, Thin fit or No fit), its prose, one chip per creative
  concept, and the brand in a line (``## About <brand>``);
- **Creative concepts**: one card per connection ``## `` section, in the
  markdown's order, which IS the ranking: the creator's moment with its
  ``&t=`` link, the dated moments that back it, the concept, the optional
  labelled sample line, the Do / Don't pair;
- **On the channel already**: where the brand or its category already
  appears on the channel, when the markdown has that section;
- **Who they are**: the ``## About <creator>`` prose, then the facts that
  section lists by id, in a recent and a background group, each dated by the
  upload it was said in (tier ``children`` / ``location`` never enter);
- **People in their videos**: who the usable facts name;
- **Creative guardrails** and **Good to know when booking**;
- **How this map was built**: the transcript coverage and "absence is not
  evidence".

Nothing on the page asks the reader to confirm a fact with the creator's
team: a fact the ledger could not confirm is never on it.

``--check`` validates the markdown against this contract (frontmatter, the
required sections, a timestamped link inside every connection's blockquote,
no price language), prints the problems and exits 3 without writing.

``--brief`` renders the OTHER deliverable, the creator-friendly brief, from
``<corpus>/creator-brief-<brand_id>.md``::

    build_html.py --brief --in .corpus/<id>/creator-brief-<brand>.md \\
        --facts <ledger> --connections .corpus/<id>/connections-<brand>.md \\
        [--input .corpus/<id>/creator-brief-input-<brand>.json] [--check]

Six sections in a fixed order (Who is the brand, The creative ask, Key
talking points, Requirements, Don't do, Creative approval process), written
for the creator's eyes: every quote is the creator's own verified words with
its timestamped link, the brand's supplied lines appear verbatim, and nothing
written for the brand's or the account manager's eyes (strength tags,
provenance labels, ids, filenames, sponsorship patterns) is allowed on it.
The output is named by names, ``<brand>-creator-brief-<creator>.html``,
because it is an attachment. ``--check`` applies the same rules and exits 3.

Facts at tier ``children`` or ``location`` never enter the who-they-are
section (they are withheld from brand-facing angles by default); ``clinical``
does, carrying its tier badge, per ``references/evidence-rules.md``.

Fonts load from Google Fonts with system fallbacks declared, so the page reads
the same offline; nothing else is fetched and there is no script.
"""
from __future__ import annotations

import argparse
import datetime as dt
import difflib
import gzip
import html
import json
import pathlib
import re
import sys
import time
import urllib.parse
from collections import Counter, defaultdict

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import tier_hint  # sibling module  # noqa: E402
from store_io import read_ledger  # sibling module  # noqa: E402
from verify_quotes import locate  # sibling module; the one quote matcher  # noqa: E402
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "_shared"))
import tl_data  # noqa: E402

SKILL = "tl-brand-creator-connection"

BADGES = {
    "direct": "direct",
    "adjacent": "adjacent",
    "category precedent": "precedent",
    "category-precedent": "precedent",
    # a concept built on a moment where the creator names the brand, unpaid
    "brand moment": "brandmoment",
    # strength: `strong` when the moment puts the creator where the product
    # is used, or the brand already appears on the channel unpaid; `thin`
    # when the link runs only through the channel's premise or a generic
    # trait. The heading carries both: `<name> · **adjacent** · **thin**`.
    "strong": "strong",
    "thin": "thin",
    "thin fit": "thinfit",
    "thin-fit": "thinfit",
    "confirmed": "confirmed",
    "unconfirmed": "unconfirmed",
    "co-host": "confirmed",
    "shared": "confirmed",
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
# The "who they are" run renders the ledger's `selected` facts; the merge
# pass owns that pick (SELECTED_TARGET, 40) and
# this is only the render cap, so it matches. The per-domain cap stops one
# talkative domain owning the strip; 8 of 12 domains at most.
WHO_MAX_FACTS = 40
WHO_MAX_PER_DOMAIN = 8
# The page's "Who they are" is a short introduction, not the ledger: the map
# names at most this many facts, and the fallback for a map that names none
# shows the same number.
WHO_PAGE_MAX = 10
# The verdict a map's `## Verdict` opens with. It must agree with the cards:
# any strong concept is a strong fit, thin concepts only are a thin fit, and
# no concepts at all are no fit.
VERDICTS = ("strong fit", "thin fit", "no fit")
# Concepts: at most this many `thin` cards; with no strong one the Verdict
# says thin fit.
MAX_THIN = 2
STRENGTHS = ("strong", "thin")

FONTS = ("https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,500;9..144,600"
         "&family=Source+Sans+3:ital,wght@0,400;0,600;1,400&family=IBM+Plex+Mono:wght@400;500"
         "&display=swap")

# the page stylesheet, read once at import
CSS = pathlib.Path(__file__).with_name("page.css").read_text(encoding="utf-8")


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
    # escape once for attribute context, a quote in a crafted link target
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
        if in_list and out and out[-1].endswith("</li>"):
            # a wrapped bullet: the continuation line belongs to the item, not
            # to a paragraph after the list (otherwise "Where this could go
            # wrong" is shredded into one-line <li>s with orphan <p>s between them)
            out[-1] = out[-1][:-len("</li>")] + " " + inline(stripped) + "</li>"
            continue
        close_list()
        para.append(stripped)
    close_para(), close_list(), close_quote()
    return "\n".join(out)


def split_sections(body_html: str) -> tuple[str, list[tuple[str, str]]]:
    """``(intro, [(title, rest), …])``: whatever precedes the first ``## ``
    section stays prose (the header lines, or a no-fit verdict); each section
    is one (title, body) pair in the markdown's order."""
    parts = re.split(r"(?=<h2>)", body_html)
    sections: list[tuple[str, str]] = []
    for chunk in parts[1:]:
        m = re.match(r"<h2>(.*?)</h2>\n?(.*)", chunk, re.S)
        if not m:
            continue
        sections.append((m.group(1), m.group(2).strip()))
    return parts[0].strip(), sections


def plain(title_html: str) -> str:
    """A section heading as text: tags dropped, entities decoded."""
    return html.unescape(re.sub(r"<[^>]+>", "", title_html)).strip()


def is_about(title_html: str) -> bool:
    """``## About <name>``: a context strip, never a numbered card. Covers
    both the creator and the brand introductions."""
    return plain(title_html).lower().startswith("about ")


def is_thesis(title_html: str) -> bool:
    """``## Verdict`` (or the older ``## Thesis``): the page's lead argument,
    rendered in the verdict panel at the top."""
    return plain(title_html).lower().rstrip(":").strip() in (
        "verdict", "the verdict", "thesis", "core thesis", "the thesis")


def is_caveat(title_html: str) -> bool:
    """``## Creative guardrails`` (or the older ``## Where this could go
    wrong``): what the integration must avoid. It is a ``## `` section like
    any other in the markdown, but it must NEVER render as a concept: a
    caveat sitting among the concepts reads as an angle."""
    t = plain(title_html).lower()
    return any(k in t for k in ("guardrail", "could go wrong", "does not connect",
                                "doesn't connect", "what does not fit",
                                "mismatch", "caveat"))


def is_on_channel(title_html: str) -> bool:
    """``## Done this before`` (or the older ``## On the channel already``):
    the creator's past partnerships in the brand's category and the brand's
    unpaid moments on the channel. Evidence, never a concept."""
    t = plain(title_html).lower()
    return t.startswith("on the channel") or "done this before" in t


def is_booking(title_html: str) -> bool:
    """``## Good to know when booking``: commercial facts a brand needs before
    it books (another brand in its category sponsoring the channel), never a
    concept."""
    t = plain(title_html).lower()
    return t.startswith("good to know") or "when booking" in t


def names_creator(title_html: str, *creators: str) -> bool:
    """Does this ``## About …`` heading introduce the creator rather than the
    brand? Compared on the names (the channel's, the host's) so a brand
    called "About Time" cannot win."""
    t = plain(title_html).lower()
    # whole words: a host called Sam does not make "About Samsung" theirs
    return any(c and re.search(rf"(?<!\w){re.escape(c)}(?!\w)", t)
               for c in (str(x or "").strip().lower() for x in creators))


def about_block(sections: list[tuple[str, str]]) -> str:
    """A context strip: plain prose, never a card."""
    blocks = [f'<div class="about"><h3>{title}</h3>{rest}</div>'
              for title, rest in sections]
    return "".join(blocks)


def verdict_label(sections: list[tuple[str, str]]) -> str | None:
    """The verdict the ``## Verdict`` section opens with, lower case: one of
    ``VERDICTS``, or None when its first paragraph does not start with one."""
    if not sections:
        return None
    m = re.search(r"<p>(.*?)</p>", sections[0][1], re.S)
    first = plain(m.group(1)).lower() if m else ""
    return next((v for v in VERDICTS if first.startswith(v)), None)


def _strip_verdict(body: str) -> str:
    """The verdict prose without its opening label: the panel prints the
    label as a pill, so the paragraph would otherwise repeat it."""
    def cut(m: re.Match) -> str:
        rest = re.sub(r"^\s*(?:<strong>|<span[^>]*>)?\s*(?:strong|thin|no)[ -]fit\s*[.:]?\s*"
                      r"(?:</strong>|</span>)?\s*[.:]?\s*", "", m.group(1), count=1, flags=re.I)
        return f"<p>{rest}</p>" if rest.strip() else ""
    return re.sub(r"<p>(.*?)</p>", cut, body, count=1, flags=re.S)


_INTERNAL_BADGES = ("badge-direct", "badge-adjacent", "badge-precedent", "badge-brandmoment",
                    "badge-strong")


def concept_parts(title_html: str) -> tuple[str, list[str], list[str]]:
    """``(name, badges, words)`` of a connection heading ``<name> · **<route>** ·
    **<type>** · **<strength>**``: the plain name, the rendered badges, and
    the tags that are not badges (the route: the kind of video the concept
    is, "Challenge series", "After the workout")."""
    title = re.sub(r"^\d+[.)]\s*", "", title_html)
    parts = [p.strip() for p in no_dashes(title, " · ").split("·")]
    badges = [p for p in parts[1:] if p and 'class="badge' in p]
    words = [plain(p) for p in parts[1:] if p and 'class="badge' not in p and plain(p)]
    return parts[0], badges, words


def concept_route(title_html: str) -> str:
    """The concept's route, the kind of video it is, lower case; "" when the
    heading names none."""
    return " ".join(concept_parts(title_html)[2]).strip().lower()


def concept_name(title_html: str) -> tuple[str, str]:
    """``(name, tags)``: the plain name, and what the brand sees beside it:
    the route, and the strength only when it is thin. The concept type and a
    strong tag are the writer's bookkeeping, not the reader's."""
    name, badges, words = concept_parts(title_html)
    shown = [f'<span class="badge badge-route">{html.escape(w)}</span>' for w in words]
    shown += [b for b in badges if not any(c in b for c in _INTERNAL_BADGES)]
    return name, " ".join(shown)


def verdict_panel(thesis: list[tuple[str, str]], conns: list[tuple[str, str]],
                  brand_about: list[tuple[str, str]]) -> str:
    """The page's lead: the verdict as a pill, the argument, one chip per
    concept, and the brand in a line. Deliberately the most prominent block
    on the page: it is what the reader acts on."""
    if not thesis and not conns:
        return ""
    label = verdict_label(thesis)
    pill = (f'<span class="pill pill-{label.split()[0]} pill-big">{html.escape(label.capitalize())}</span>'
            if label else "")
    count = (f'<span class="vmeta">{len(conns)} creative concept{"s" if len(conns) != 1 else ""}</span>'
             if conns else "")
    body = "".join(_strip_verdict(rest) if i == 0 else rest
                   for i, (_, rest) in enumerate(thesis))
    chips = []
    for i, (title, _) in enumerate(conns, 1):
        name, tags = concept_name(title)
        chips.append(f'<a class="chip" href="#c{i}"><span class="k">Concept {i}</span>'
                     f'<b>{name}</b>{tags}</a>')
    brand = "".join(f'<div class="brand">{rest}</div>' for _, rest in brand_about)
    return ('<section class="verdict">'
            + (f'<div class="verdict-top">{pill}{count}</div>' if pill or count else "")
            + f'<div class="thesis">{body}</div>'
            + (f'<div class="chips">{"".join(chips)}</div>' if chips else "")
            + brand + '</section>')


def caveat_block(sections: list[tuple[str, str]]) -> str:
    """"Creative guardrails", after the concepts and outside the ranking:
    what the integration must avoid, written for the brand."""
    if not sections:
        return ""
    bodies = "".join(rest for _, rest in sections)
    title = plain(sections[0][0]) or "Creative guardrails"
    return (f'<h2>{html.escape(title)}</h2>'
            f'<div class="caveat">{bodies}</div>')


def plain_block(sections: list[tuple[str, str]], cls: str) -> str:
    """A titled section printed as written: "On the channel already" and
    "Good to know when booking"."""
    return "".join(f'<h2>{html.escape(plain(title))}</h2><div class="{cls}">{rest}</div>'
                   for title, rest in sections)


_BLOCKQUOTE = re.compile(r"<blockquote>.*?</blockquote>", re.S)


_DASH_SPACED = re.compile(r"\s+[\u2014\u2013]\s+")
_DASH_ANY = re.compile(r"[\u2014\u2013]")


def no_dashes(text: str, sep: str = ", ") -> str:
    """Em and en dashes never reach a page. A spaced dash becomes ``sep`` (a
    middle dot on a card heading, where the spec puts one between the tags;
    a comma in prose) and a dash inside a word becomes a plain hyphen."""
    return _DASH_ANY.sub("-", _DASH_SPACED.sub(sep, text))


# the labelled lines of a concept card, as the map writes them
_CARD_FIELD = re.compile(
    r"<p>(The moment|The concept|What meets it|How it could be used"
    r"|Sample (?:line|read)[^:<]*|Do not|Don[’']t|Do):\s*", re.I)


def _card_body(rest: str) -> str:
    """A concept's body with its labelled lines marked up: each label set
    apart, the sample line boxed, and the Do / Don't pair side by side."""
    def field(m: re.Match) -> str:
        label = m.group(1)
        low = label.lower()
        cls = ("sample" if low.startswith("sample") else
               "dont" if low in ("don't", "do not") else
               "do" if low == "do" else "field")
        return f'<p class="f f-{cls}"><span class="lbl">{label}</span> '
    body = _CARD_FIELD.sub(field, rest)
    body = re.sub(r'((?:<p class="f f-(?:do|dont)">.*?</p>\s*){2})',
                  r'<div class="dodont">\1</div>', body, flags=re.S)
    return body.replace("<ul>", '<ul class="more">')


def concept_cards(sections: list[tuple[str, str]], intro: str = "") -> str:
    """Each connection section becomes one concept card; the section order IS
    the ranking, so the cards are numbered Concept 1, 2, 3."""
    cards = []
    for i, (title, rest) in enumerate(sections, 1):
        name, tags = concept_name(title)
        cards.append(f'<article class="card" id="c{i}"><div class="card-head">'
                     f'<span class="k">Concept {i}</span>{tags}</div>'
                     f'<h3>{name}</h3>{_card_body(rest)}</article>')
    out = f'<div class="prose">{intro}</div>' if intro else ""
    if cards:
        out += f'<div class="conn">{"".join(cards)}</div>'
    return out


# --------------------------------------------------------------------------- #
# ledger data
# --------------------------------------------------------------------------- #
def load_ledger(facts_path: pathlib.Path | None,
                meta_path: pathlib.Path | None) -> tuple[list[dict] | None, dict]:
    """``(facts, meta)`` from the ledger, its first line is the meta record.
    ``--meta`` is only read when the ledger predates the header (legacy)."""
    if facts_path is None:
        return None, (json.loads(pathlib.Path(meta_path).read_text(encoding="utf-8"))
                      if meta_path else {})
    meta, facts = read_ledger(facts_path)
    if meta is None and meta_path:
        meta = json.loads(pathlib.Path(meta_path).read_text(encoding="utf-8"))
    return facts, meta or {}


def tier_of(fact: dict) -> str:
    tier = str(fact.get("sensitivity") or "").lower()
    if tier in TIER_ORDER:
        return tier
    # a ledger written against the old boolean: the flag alone cannot say
    # which withheld tier, so it renders as withheld without naming one
    return "withheld" if fact.get("sensitive") else "none"


def bio_corroborated(fact: dict, index: dict[str, dict]) -> bool:
    """Whether a bio fact is really corroborated, re-derived here rather than
    read off ``confidence``.

    The merge pass confirms a bio fact when a transcript fact says the same
    thing, but quote verification runs afterwards and can reject that quote, and a later run can drop the transcript fact entirely. So the page asks the
    question again from the evidence link: is the named fact still in the
    ledger, is it a transcript fact, and did its quote survive verification."""
    target = index.get(str(fact.get("corroborated_by") or ""))
    if target is None or target.get("provenance") != "transcript":
        return False
    # a retired fact keeps its quote as history, but its evidence was rejected
    if target.get("retired_reason"):
        return False
    if str((target.get("verify") or {}).get("match") or "").lower() == "no":
        return False
    return bool(target.get("quote"))


def unverified_bio(fact: dict, index: dict[str, dict]) -> bool:
    """The creator's own written words that no upload corroborates."""
    return fact.get("provenance") == "bio" and not bio_corroborated(fact, index)


def angle_ineligible_reason(fact: dict, index: dict[str, dict] | None = None) -> str | None:
    """Why a fact may not support a brand-facing angle.

    This is the single publication-policy gate for the connections page and
    creator brief. Sensitive facts can still inform the page's risk warning;
    they may not become a positive angle or talking point unless this gate
    allows them.
    """
    if fact.get("retired_reason"):
        return "retired after its evidence was rejected"
    if fact.get("superseded_by"):
        return f"superseded by {fact.get('superseded_by')}"
    if fact.get("ended"):
        return "ended: the evidence shows it is over"
    if str(fact.get("confidence")) != "confirmed":
        return "unconfirmed"
    if fact.get("staged_only"):
        return "said only inside a staged premise"
    tier = tier_of(fact)
    if tier in WITHHELD or tier == "withheld":
        return f"withheld tier {tier}"
    if (tier == "clinical"
            and str(fact.get("provenance") or "transcript") == "transcript"
            and int(fact.get("recurrence") or 0) < 3):
        return "clinical fact discussed in fewer than three videos"
    if index is not None and unverified_bio(fact, index):
        return "written bio claim not corroborated by a transcript"
    # the protective backstops the merge pass shares: a fact about a child
    # left at tier none, or one carrying a sum of money, is in the ledger and
    # never on a brand-facing page
    if tier_hint.names_child(fact.get("claim"), fact.get("quote"), fact.get("source_excerpt")):
        return "names a child"
    if tier_hint.names_money(fact.get("claim"), fact.get("quote"), fact.get("source_excerpt")):
        return "names a sum of money"
    return None


def tier_badge(fact: dict) -> str:
    tier = tier_of(fact)
    if tier == "none":
        return ""
    label = tier if tier in TIER_ORDER else "withheld"
    return badge(label) or ""


def confidence_badge(fact: dict) -> str:
    """``unconfirmed`` on a fact that is not confirmed. The page gate keeps
    such facts off the page, so this is a backstop for an older ledger."""
    return "" if fact.get("confidence") == "confirmed" else (badge("unconfirmed") or "")


def speaker_badge(fact: dict) -> str:
    """Who said it on a multi-host channel: the second host or both."""
    who = str(fact.get("speaker") or "host")
    return "" if who == "host" else (badge("co-host" if who == "cohost" else "shared") or "")


RECENT_MONTHS = 24


def is_recent(fact: dict, today: str | None = None) -> bool:
    """``last_seen`` inside the last ``RECENT_MONTHS`` of today. A fact with
    no date is not recent. A fact from a ledger saved before ``last_seen``
    existed falls back to ``published``, which is never later."""
    seen = str(fact.get("last_seen") or fact.get("published") or "")[:10]
    today = (today or dt.date.today().isoformat())[:10]
    if not seen:
        return False
    y, m = int(today[:4]), int(today[5:7])
    m -= RECENT_MONTHS
    while m <= 0:
        m += 12
        y -= 1
    return seen >= f"{y:04d}-{m:02d}-{today[8:10]}"


# the cast-sheet role a relation must carry for an appearance to count: a
# crew member who shares the cousin's name is not the cousin
_CAST_ROLE = {**{r: "family" for r in ("cousin", "sister", "brother", "mom", "mum", "mother", "dad",
                                       "father", "aunt", "uncle", "grandma", "grandpa", "grandmother",
                                       "grandfather", "girlfriend", "boyfriend", "fiancée", "fiancé",
                                       "wife", "husband")},
              **{r: "friend" for r in ("friend", "best friend", "hometown friend", "roommate",
                                       "roommate friend", "childhood friend")}}
# relations that never lapse: they carry no "as of" year
_KIN = {"cousin", "sister", "brother", "mom", "mum", "mother", "dad", "father", "aunt", "uncle",
        "grandma", "grandpa", "grandmother", "grandfather", "son", "daughter"}
_PARTNER_UP = re.compile(r"\b(fianc[eé]e?|engaged|wife|husband|married)\b", re.I)


def people_section(facts: list[dict] | None, index: dict[str, dict],
                   heading: str = "People in their videos",
                   seen: dict[str, str] | None = None) -> str:
    """The people the creator's quotes name, from facts the page may use:
    one row per exact spelling with its relation words, and the newest upload
    that shows them: the fact's own upload, a later one the probe found saying
    it again (``last_seen``), or a later one whose cast sheet names them
    (``seen``, from cast.json). A name with no relation is left out. A
    relation said only "as of" an older video carries its year, and a
    girlfriend or boyfriend becomes the fiance(e), wife or husband a newer
    fact names when they are the only partner in the table."""
    rows: dict[str, dict] = {}
    for f in facts or []:
        if angle_ineligible_reason(f, index) is not None:
            continue
        for p in f.get("people") or []:
            name = str(p.get("name") or "").strip()
            if not name:
                continue
            row = rows.setdefault(name, {"rel": [], "last": "", "said": ""})
            rel = str(p.get("relation") or "")
            if rel and rel.lower() not in _KIN and str(f.get("claim") or "").lower().startswith("as of this video") \
                    and not is_recent({"last_seen": f.get("last_seen") or f.get("published")}):
                rel = f"{rel} ({str(f.get('published') or '')[:4]})"
            if rel and rel not in row["rel"]:
                row["rel"].append(rel)
            row["last"] = max(row["last"], str(f.get("published") or "")[:10],
                              str(f.get("last_seen") or "")[:10])
            if rel:
                row["said"] = max(row["said"], str(f.get("published") or "")[:10])
    for name, row in rows.items():
        roles = {_CAST_ROLE.get(r.split(" (")[0].lower()) for r in row["rel"]} - {None}
        for day, role in (seen or {}).get(name.lower()) or []:
            if role in roles:
                row["last"] = max(row["last"], str(day)[:10])
    rows = {n: r for n, r in rows.items() if r["rel"]}
    partners = [n for n, r in rows.items()
                if any(x in ("girlfriend", "boyfriend") for x in r["rel"])]
    if len(partners) == 1:
        row = rows[partners[0]]
        newer = sorted((f for f in facts or [] if angle_ineligible_reason(f, index) is None
                        and not f.get("people") and _PARTNER_UP.search(str(f.get("claim") or ""))
                        and str(f.get("last_seen") or f.get("published") or "")[:10] > row["said"]),
                       key=lambda f: str(f.get("last_seen") or f.get("published") or ""))
        if newer:
            word = _PARTNER_UP.search(str(newer[-1].get("claim"))).group(1).lower()
            her = "girlfriend" in row["rel"]
            up = {"fiance": "fiancée" if her else "fiancé", "fiancé": "fiancée" if her else "fiancé",
                  "fiancee": "fiancée", "fiancée": "fiancée", "engaged": "fiancée" if her else "fiancé",
                  "married": "wife" if her else "husband"}.get(word, word)
            row["rel"] = [up if x in ("girlfriend", "boyfriend") else x for x in row["rel"]]
    if not rows:
        return ""
    trs = "".join(
        f'<tr><td>{html.escape(n)}</td><td>{html.escape(", ".join(r["rel"]))}</td>'
        f'<td class="n">{html.escape(r["last"][:7])}</td></tr>'
        for n, r in sorted(rows.items(), key=lambda kv: (kv[1]["last"], kv[0]), reverse=True))
    return (f'<h3>{html.escape(heading)}</h3><div class="tablewrap"><table class="people"><thead><tr>'
            '<th>Name</th><th>Who</th><th>Seen in</th></tr></thead>'
            f'<tbody>{trs}</tbody></table></div>')


def cast_appearances(corpus_dir: pathlib.Path | None) -> dict[str, list[tuple[str, str]]]:
    """Every upload each person appears in, by the cast sheets: name or
    alias, lower-cased, to (publish date, the sheet's role)."""
    if corpus_dir is None:
        return {}
    try:
        cast = json.loads((corpus_dir / "cast.json").read_text(encoding="utf-8"))
        dates = {}
        with gzip.open(corpus_dir / "corpus.jsonl.gz", "rt", encoding="utf-8") as fh:
            for line in fh:
                r = json.loads(line)
                dates[str(r.get("id") or "").split(":")[-1]] = str(r.get("publication_date") or "")[:10]
    except (OSError, ValueError):
        return {}
    out: dict[str, list[tuple[str, str]]] = {}
    for vid, sheet in (cast or {}).items():
        day = dates.get(str(vid), "")
        if not day:
            continue
        for g in (sheet or {}).get("guests") or []:
            for n in [g.get("name")] + list(g.get("aliases") or []):
                key = str(n or "").strip().lower()
                if key:
                    out.setdefault(key, []).append((day, str(g.get("role") or "")))
    return out


def built_footer(meta: dict) -> str:
    """"How this map was built": what the quotes come from, how the dates
    are read, and the line that bounds every absence on the page."""
    cov = meta.get("coverage") or {}
    n = cov.get("videos_with_transcript")
    window = meta.get("corpus_window")
    span = ""
    if isinstance(window, (list, tuple)) and any(window):
        lo, hi = (list(window) + [None, None])[:2]
        span = f" ({str(lo or '?')[:7]} to {str(hi or '?')[:7]})"
    creator = html.escape(str(meta.get("channel_name") or "the creator"))
    videos = f"{n} transcribed videos" if n else "their transcribed videos"
    return ('<h2>How this map was built</h2><div class="ledger"><p>'
            f"Built from {creator}'s own words across {videos}{span}. Every quote is "
            "word for word from the video at the linked time, and every date is the "
            "date that video was published. Transcripts do not cover every upload, "
            "so absence is not evidence.</p></div>")


# --------------------------------------------------------------------------- #
# who they are (connections page)
# --------------------------------------------------------------------------- #
def pick_who(facts: list[dict], *, max_facts: int = WHO_MAX_FACTS,
             per_domain: int = WHO_MAX_PER_DOMAIN) -> list[tuple[str, list[dict]]]:
    """Top facts by domain: selected first, then CONFIRMED, then recurrence.

    Superseded facts, the withheld tiers and `staged_only` facts never appear;
    the last of those is what `profile-spec.md` means by "never quoted on a
    brand-facing page", and this page is brand-facing.

    Confidence ranks above recurrence, matching the order `merge_pass expand`
    already applies when it owns `selected`. Ranking it below would put a
    well-repeated unsettled claim ahead of a confirmed one, and could render
    two contradicting unconfirmed relationship claims side by side while
    confirmed facts that survived the per-domain cap went unused. The merge
    pass deliberately leaves such a contradiction unresolved and off the
    connection cards; the renderer must not put it back.
    """
    index = {str(f.get("fact_id")): f for f in facts}
    usable = [f for f in facts
              if angle_ineligible_reason(f, index) is None]

    def key(f: dict):
        return (bool(f.get("selected")), f.get("confidence") == "confirmed",
                int(f.get("recurrence") or 0))

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
    # domains ordered by how much of the ledger they hold, what the creator
    # talks about most comes first
    weight = Counter(str(f.get("domain") or "other") for f in usable)
    return sorted(by_domain.items(), key=lambda kv: -weight[kv[0]])


def short_quote(quote: str, words: int = 14) -> str:
    toks = quote.split()
    return " ".join(toks[:words]) + ("…" if len(toks) > words else "")


def pick_who_flat(facts: list[dict], *, max_facts: int = WHO_MAX_FACTS,
                  per_domain: int = WHO_MAX_PER_DOMAIN) -> list[dict]:
    """The same picks as ``pick_who``, flattened back into one ranked run.

    The domain grid this replaces read as a database view of a person rather
    than an introduction. The per-domain cap is kept, because it is what stops
    one talkative domain owning the whole strip, but the domains stop being
    headings."""
    out: list[dict] = []
    for _, items in pick_who(facts, max_facts=max_facts, per_domain=per_domain):
        out.extend(items)
    # the same order as pick_who's own key, or the flattening would undo it
    out.sort(key=lambda f: (bool(f.get("selected")),
                            f.get("confidence") == "confirmed",
                            int(f.get("recurrence") or 0)), reverse=True)
    return out[:max_facts]


# A "Who they are" line in the map: fact ids joined by "+", then the line
# the page prints, e.g. "- f021+f010+f038: Grew up on a farm, now lives in the city."
_WHO_LINE = re.compile(r"<li>\s*(f\d{1,4}(?:\s*\+\s*f\d{1,4})*)\s*:\s*(.*?)</li>", re.S)


def who_lines(about_html: str) -> tuple[str, list[tuple[list[str], str]]]:
    """``(prose, [(fact ids, line), ...])`` from the ``## About <creator>``
    section: the prose stays the introduction, and each bullet that opens
    with fact ids is one line of "Who they are"."""
    lines = [([x.strip() for x in m.group(1).split("+")], m.group(2).strip())
             for m in _WHO_LINE.finditer(about_html)]
    prose = re.sub(r"<ul>\s*</ul>", "", _WHO_LINE.sub("", about_html))
    return prose.strip(), lines


def source_label(url: str) -> str:
    """A short name for where a social or web fact was read."""
    host = urllib.parse.urlsplit(url).netloc.lower().removeprefix("www.")
    for key, label in (("wikipedia", "Wikipedia"), ("instagram", "Instagram"),
                       ("tiktok", "TikTok"), ("twitter", "X"), ("x.com", "X"),
                       ("linkedin", "LinkedIn"), ("facebook", "Facebook")):
        if key in host:
            return label
    return host or "web"


_HISTORY_SPAN = re.compile(r"\b(said from|from \w+ \d{4} to|until|used to|no longer|in \d{4})\b", re.I)


def story_ok(fact: dict, index: dict[str, dict]) -> bool:
    """A fact the story may list: one the page may use, or a phase that has
    ended or been replaced, which stays as dated history and is never a
    current connection."""
    why = angle_ineligible_reason(fact, index)
    if why is None:
        return True
    if not (why.startswith("superseded") or why.startswith("ended")):
        return False
    rest = dict(fact, superseded_by=None, ended=False)
    return angle_ineligible_reason(rest, index) is None


def _who_item(ids: list[str], line: str, index: dict[str, dict]) -> dict | None:
    """One renderable line: the usable facts it names, its date (the newest
    upload among them), the first quote, and the sources. None when no
    named fact may appear on the page."""
    usable = [index[i] for i in ids if i in index and story_ok(index[i], index)]
    if not usable:
        return None
    # one fact speaks for the line: the newest, so its date, quote and link agree
    spoken = sorted((f for f in usable if f.get("quote")),
                    key=lambda f: str(f.get("published") or ""), reverse=True)
    date = str(spoken[0].get("published") or "")[:10] if spoken else ""
    sources = []
    if spoken and str(spoken[0].get("url") or "").lower().startswith(("http://", "https://")):
        sources.append(f'<a href="{html.escape(str(spoken[0]["url"]), quote=True)}">Watch</a>')
    for f in usable:
        url = str(f.get("source_url") or "")
        if not f.get("quote") and url.lower().startswith(("http://", "https://")):
            sources.append(f'<a href="{html.escape(url, quote=True)}">'
                           f'{html.escape(source_label(url))}</a>')
    return {"date": date, "line": line, "quote": str(spoken[0]["quote"]) if spoken else "",
            "sources": sources, "facts": usable}


def display_name(fm: dict, meta: dict, creator: str) -> str:
    """The name the page's headings use: the host's first name when the map
    gives one (``creator_name``), else the channel name."""
    return str(fm.get("creator_name") or meta.get("creator_name") or creator or "the creator").strip()


def who_intro(about_html: str, name: str) -> str:
    """"Who <name> is": the ``## About <creator>`` prose, at the top of the
    page, without its fact lines (those are the story, lower down)."""
    prose, _lines = who_lines(about_html)
    if not prose:
        return ""
    return f'<h2>Who {html.escape(name)} is</h2><div class="intro">{prose}</div>'


def _years(rows: list[dict]) -> str:
    ys = sorted({str(it["date"])[:4] for it in rows if str(it.get("date") or "")[:4].isdigit()})
    if not ys:
        return ""
    return ys[0] if ys[0] == ys[-1] else f"{ys[0]} to {ys[-1]}"


def who_they_are(facts: list[dict], meta: dict, about_html: str = "",
                 heading: str = "Who they are", with_prose: bool = True) -> str:
    """The person behind the channel: the map's prose, then the facts it
    names, at most ``WHO_PAGE_MAX``, split into recent and background and
    newest first. A map that names no facts falls back to the ledger's
    ranked picks, each line its own claim."""
    index = {str(f.get("fact_id")): f for f in facts}
    prose, lines = who_lines(about_html)
    if not lines:
        lines = [([str(f.get("fact_id"))], html.escape(str(f.get("claim") or "")))
                 for f in pick_who_flat(facts)]
    items = [it for it in (_who_item(ids, line, index) for ids, line in lines) if it]
    items = items[:WHO_PAGE_MAX]
    head = f'<h2>{html.escape(heading)}</h2>' + (f'<div class="intro">{prose}</div>'
                                                 if prose and with_prose else "")
    if not items:
        return head + '<p class="empty">The ledger holds no facts that can appear on a brand-facing page.</p>'
    recent = [it for it in items if it["date"] and is_recent({"published": it["date"]})]
    older = [it for it in items if it not in recent]

    def group(title: str, rows: list[dict]) -> str:
        if not rows:
            return ""
        rows = sorted(rows, key=lambda it: it["date"], reverse=True)
        lis = []
        for it in rows:
            q = (f'<span class="q">“{html.escape(short_quote(it["quote"]))}”</span>'
                 if it["quote"] else "")
            # the story is brand-facing: an everyday lifestyle fact carries no tag,
            # a clinical one keeps its warning
            badges = "".join(speaker_badge(f) + (tier_badge(f) if tier_of(f) != "lifestyle" else "")
                             for f in it["facts"][:1])
            lis.append(f'<li><span class="date">{html.escape(it["date"][:4] or "web")}</span>'
                       f'<span class="claim">{it["line"]}{badges}{q}</span>'
                       f'<span class="src">{" · ".join(it["sources"])}</span></li>')
        return f'<div class="group"><h3>{title}</h3><ul class="who-run">{"".join(lis)}</ul></div>'

    return (head + '<div class="facts">'
            + group(f"Recent, {_years(recent)}" if _years(recent) else "Recent", recent)
            + group(f"Background, {_years(older)}" if _years(older) else "Background", older)
            + '</div>')


# --------------------------------------------------------------------------- #
# page
# --------------------------------------------------------------------------- #
def page_body(title: str, eyebrow: str, header_extra: str, body: str) -> str:
    """The page's content without the document shell: what an Artifact host
    wraps in its own doctype/head/body."""
    return f"""<main>
<header>
<p class="eyebrow">{html.escape(eyebrow)}</p>
<h1>{html.escape(title)}</h1>
{header_extra}
</header>
{body}
</main>
"""


def page_html(title: str, eyebrow: str, header_extra: str, body: str) -> str:
    # the last gate: nothing the writer typed, and nothing a template line
    # carried, puts an em or en dash on a page
    title, header_extra, body = no_dashes(title), no_dashes(header_extra), no_dashes(body)
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
{page_body(title, eyebrow, header_extra, body)}</body>
</html>
"""


def page_fragment(title: str, eyebrow: str, header_extra: str, body: str) -> str:
    """The same page as a body fragment: `<title>` and `<style>` first (the
    Artifact tool reads the title from the first 8 KB and supplies the
    document shell itself), then the content. Publishing the full document
    through that tool nests one HTML document inside another, and the page
    then cannot be published at all."""
    title, header_extra, body = no_dashes(title), no_dashes(header_extra), no_dashes(body)
    return (f"<title>{html.escape(title)}</title>\n"
            f'<link rel="stylesheet" href="{FONTS}">\n'
            f"<style>{CSS}</style>\n"
            + page_body(title, eyebrow, header_extra, body))


def default_out(in_path: pathlib.Path, facts_path: pathlib.Path | None,
                fm: dict) -> pathlib.Path:
    """The deliverable lands next to the ledger as
    ``<channel_id>-<brand_id>-connections.html``; without a ledger it lands
    next to its own markdown."""
    if facts_path is None:
        return in_path.with_suffix(".html")
    channel = re.sub(r"-facts$", "", facts_path.stem)
    brand = str(fm.get("brand_id") or "").strip()
    if not brand:
        m = (re.search(r"^connections-(.+)$", in_path.stem)
             or re.search(r"^\d+-([^-]+)-connections$", in_path.stem))
        brand = m.group(1) if m else ""
    name = (f"{channel}-{brand}-connections.html" if brand
            else f"{in_path.stem}.html")
    return facts_path.parent / name


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
        chips.append(f"prepared {fm['brand_read_date']}")
    header_extra = (f'<ul class="meta">{"".join(f"<li>{html.escape(c)}</li>" for c in chips)}</ul>'
                    if chips else "")
    intro, sections = split_sections(body_html)

    # One deliverable, written for the brand, in the order it reads: who the
    # creator is and what they have done in the category first, then the
    # verdict and its concepts, then the creator's story and the people in
    # it, then what to avoid and what to know before booking.
    creator_about, brand_about, thesis, caveats, conns = [], [], [], [], []
    on_channel, booking = [], []
    for sec in sections:
        if is_thesis(sec[0]):
            thesis.append(sec)
        elif is_caveat(sec[0]):
            caveats.append(sec)
        elif is_on_channel(sec[0]):
            on_channel.append(sec)
        elif is_booking(sec[0]):
            booking.append(sec)
        elif is_about(sec[0]):
            (creator_about if names_creator(sec[0], creator, str(fm.get("creator_name") or ""))
             else brand_about).append(sec)
        else:
            conns.append(sec)

    creator_intro = "".join(rest for _, rest in creator_about)
    index = {str(f.get("fact_id")): f for f in (facts or [])}
    name = display_name(fm, meta, creator)
    if facts is not None:
        top = who_intro(creator_intro, name)
        story = (who_they_are(facts, {**meta, "channel_name": creator}, creator_intro,
                              heading=f"{name}'s story so far", with_prose=False)
                 + people_section(facts, index, heading=f"Who shows up in {name}'s videos",
                                  seen=meta.get("_seen")))
    else:
        top, story = about_block(creator_about), ""
    done = "".join(f'<h2>{html.escape(name)} has done this before</h2><div class="onchannel">{rest}</div>'
                   for _, rest in on_channel)
    body_out = (top + done
                + verdict_panel(thesis, conns, brand_about)
                + ("<h2>Creative concepts</h2>" if conns or intro else "")
                + concept_cards(conns, intro)
                + story
                + caveat_block(caveats)
                + plain_block(booking, "booking")
                + built_footer({**meta, "channel_name": creator}))
    return title, (page_html(title, "brand creator connection map", header_extra, body_out),
                   page_fragment(title, "brand creator connection map", header_extra, body_out))


def strength_of(title_html: str) -> str | None:
    """The strength tag on a connection heading, or None when it carries none."""
    _name, badges, _words = concept_parts(title_html)
    for s in STRENGTHS:
        if any(f"badge-{s}\"" in b for b in badges):
            return s
    return None


def _norm_words(text: str) -> str:
    # caption tags ([music], [applause]) are not words the creator said
    text = re.sub(r"\[[^\]]*\]", " ", text or "")
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", "", text.lower())).strip()


def quote_matches_ledger(quote_html: str, facts: list[dict] | None) -> dict | None:
    """The ledger fact that contains this complete quoted passage.

    Attribution links are removed, but no words from the quotation itself are
    discarded. A short excerpt may match a longer verified ledger quote; a
    longer quote with an invented ending may never match a shorter source.
    """
    if not facts:
        return None
    # The attribution link sits inside the blockquote too. Drop that complete
    # anchor, then compare the entire remaining passage.
    stripped = re.sub(r"<a\b[^>]*>.*?</a>", " ", quote_html, flags=re.S)
    q = _norm_words(re.sub(r"<[^>]+>", " ", stripped))
    if len(q.split()) < 4:
        return None
    for f in facts:
        fq = _norm_words(str(f.get("quote") or ""))
        if fq and q in fq:
            return f
    return None


def _video_and_time(url: str) -> tuple[str | None, int | None]:
    """``(video id, seconds)`` of a YouTube link; ``t=`` may be 512, 512s or 8m32s."""
    parts = urllib.parse.urlsplit(html.unescape(url or ""))
    query = urllib.parse.parse_qs(parts.query)
    vid = (query.get("v") or [None])[0]
    if vid is None and parts.netloc.endswith("youtu.be"):
        vid = parts.path.strip("/") or None
    raw = (query.get("t") or [""])[0]
    m = re.fullmatch(r"(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s?)?", raw)
    if not raw or not m or not any(m.groups()):
        return vid, None
    h, mnt, s = (int(g or 0) for g in m.groups())
    return vid, h * 3600 + mnt * 60 + s


# caption cues start on whole seconds, and a link may round either way
_CITE_SLACK_S = 2


def citation_problem(quote_norm: str, links: list[str], source_quote: str,
                     source_url: str) -> str | None:
    """Why a quote's links do not point at the evidence it quotes, or None.

    The source is the ledger fact (or the connections-map quote) the passage
    matched. Every timed link in the quote must name the source's video, at
    the source's timestamp. A shorter excerpt may start later inside the
    passage, so the link may run ahead by at most one second per word that
    precedes the excerpt: speech never runs slower than that, so a later
    timestamp is a different moment."""
    want_vid, want_t = _video_and_time(source_url)
    if want_vid is None or want_t is None:
        return "its source has no timestamped video link to check it against"
    lead = 0
    src = _norm_words(source_quote)
    pos = src.find(quote_norm) if quote_norm else -1
    if pos > 0:
        lead = len(src[:pos].split())
    for link in links:
        vid, t = _video_and_time(link)
        if t is None:
            continue
        if vid != want_vid:
            return f"links to video {vid}, but the quote is from {want_vid}"
        if not want_t - _CITE_SLACK_S <= t <= want_t + lead + _CITE_SLACK_S:
            return f"links to {t}s, but the quote is said at {want_t}s"
    return None


def quote_links(block: str) -> list[str]:
    """Every link target inside one quote block, markdown or rendered HTML."""
    return (re.findall(r'href="([^"]*)"', block)
            + re.findall(r"\]\(([^)\s]*)\)", block))


def quote_text(block_html: str) -> str:
    """The normalised quoted words of one rendered blockquote, links dropped."""
    block_html = re.sub(r"<a\b[^>]*>.*?</a>", " ", block_html, flags=re.S)
    return _norm_words(re.sub(r"<[^>]+>", " ", block_html))


def ineligible_on_page(page_text: str, facts: list[dict] | None,
                       index: dict[str, dict], seen: set[str]) -> list[tuple[dict, str]]:
    """Ledger facts whose verified quote appears anywhere on the page, quoted
    or not, that the publication gate refuses. ``seen`` holds fact ids already
    reported, so one fact is named once."""
    norm = _norm_words(page_text)
    out = []
    for f in facts or []:
        fid = str(f.get("fact_id"))
        fq = _norm_words(str(f.get("quote") or ""))
        if fid in seen or len(fq.split()) < 4 or fq not in norm:
            continue
        reason = angle_ineligible_reason(f, index)
        if reason:
            seen.add(fid)
            out.append((f, reason))
    return out


# --------------------------------------------------------------------------- #
# --check: the mechanical half of a QA pass, in the renderer
# --------------------------------------------------------------------------- #
# A second agent re-reading the first agent's page is slow and catches only
# things a script can check. These are those things. What a script
# cannot check, whether the thesis is any good, stays the connection pass's
# job and is not re-litigated by another model.
_MONEY = re.compile(r"(?<![\w-])(?:[$€£]\s?\d|\d+\s?(?:usd|eur|gbp)\b"
                    r"|\bcpm\b|\brate card\b|\bflat fee\b"
                    r"|\bper (?:video|integration|read)\b\s*[:=]?\s*[$€£\d])",
                    re.I)
# A quote's link must point at the moment it was said. The href is already
# entity-escaped by the renderer, so the separator can be "?", "&" or "&amp;".
_TIMED_LINK = re.compile(r'href="[^"]*(?:\?|&amp;|&)t=\d', re.I)


def section_kinds(md_text: str, meta: dict) -> dict[str, list]:
    """The page's sections, split by what each one is. ``conn`` is the ranked
    connections, so ``len(kinds["conn"])`` is the connection count and an
    empty one is the no-fit verdict."""
    fm, body = parse_frontmatter(md_text)
    creator = fm.get("channel_name") or meta.get("channel_name") or ""
    host = str(fm.get("creator_name") or "")
    _, sections = split_sections(render_markdown(body))

    kinds = {"thesis": [], "caveat": [], "creator": [], "brand": [], "conn": [],
             "channel": [], "booking": []}
    for sec in sections:
        if is_thesis(sec[0]):
            kinds["thesis"].append(sec)
        elif is_caveat(sec[0]):
            kinds["caveat"].append(sec)
        elif is_on_channel(sec[0]):
            kinds["channel"].append(sec)
        elif is_booking(sec[0]):
            kinds["booking"].append(sec)
        elif is_about(sec[0]):
            kinds["creator" if names_creator(sec[0], creator, host) else "brand"].append(sec)
        else:
            kinds["conn"].append(sec)
    return kinds


def probe_windows(probe: dict | None) -> list[dict]:
    """Every window the brand-moments lane returned: the moments where the
    creator does what the product enables, and the unpaid moments that name
    the brand."""
    if not isinstance(probe, dict):
        return []
    return [w for key in ("windows", "brand_windows") for w in (probe.get(key) or [])
            if isinstance(w, dict) and str(w.get("text") or "").strip()]


def probe_texts(probe: dict | None) -> list[str]:
    """The normalised text of every window the brand-moments lane returned."""
    return [_norm_words(str(w.get("text") or "")) for w in probe_windows(probe)]


def is_probe_quoted(title_html: str) -> bool:
    """A concept whose lead quote is a lane window, not a ledger fact: a
    category precedent (the creator already does what the product enables)
    or a brand moment (the creator names the brand, unpaid)."""
    t = plain(title_html).lower()
    return "precedent" in t or "brand moment" in t


# a quoted phrase inside a supporting moment or an "On the channel already"
# line, in straight or curly double quotes
_INLINE_QUOTE = re.compile(r"[\"“]([^\"“”]{12,}?)[\"”]")
# a reader is never asked to check a fact with the creator's team: a fact the
# ledger could not confirm is not on the page at all
_TO_CONFIRM = re.compile(r"\bconfirm (?:\w+ ){0,3}with (?:his|her|their|the creator'?s?) "
                         r"(?:team|management|manager)\b|\bto confirm with\b", re.I)


def supporting_problems(sections: list[tuple[str, str]], facts: list[dict] | None,
                        probe: dict | None, where: str, moments: dict | None = None) -> list[str]:
    """Quotes inside list items (a concept's further moments, the "On the
    channel already" lines) must be the creator's words a lane returned, the
    ledger holds or moment_check read and passed, and each item that quotes
    carries a link to the video."""
    if probe is None and not facts:
        return []
    texts = (probe_texts(probe) + [_norm_words(str(f.get("quote") or "")) for f in facts or []]
             + [_norm_words(str(m.get("quote") or "")) for m in (moments or {}).get("usable") or []]
             # a whole sentence may start a cue before the window does
             + [_norm_words(" ".join(str(c[1]) for c in m.get("cues") or []))
                for m in (moments or {}).get("usable") or []])
    out = []
    for title, rest in sections:
        name = plain(title)[:60]
        for li in re.findall(r"<li>(.*?)</li>", rest, re.S):
            words = html.unescape(re.sub(r"<a\b[^>]*>.*?</a>", " ", li, flags=re.S))
            quotes = [q for q in _INLINE_QUOTE.findall(re.sub(r"<[^>]+>", " ", words))
                      if len(_norm_words(q).split()) >= 4]
            if not quotes:
                continue
            if not re.search(r'href="https?://', li):
                out.append(f"{where} line quotes the creator without a link to the video: {name}")
            if probe is None:
                continue
            for q in quotes:
                if not any(_norm_words(q) in t for t in texts):
                    out.append(f"{where} quote is not in a window the brand-moments lane "
                               f"returned or a ledger fact: {q[:40]!r} ({name})")
    return out


def load_probe(in_path: pathlib.Path | None) -> dict | None:
    """``category-probe.json`` beside the map, when the probe lane wrote one."""
    if in_path is None:
        return None
    p = in_path.parent / "category-probe.json"
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else None
    except (OSError, ValueError):
        return None


def link_clean_moments(facts: list[dict] | None, moments: dict | None) -> list[dict] | None:
    """A fact whose own moment failed moment_check for its surroundings (a
    rival, an awkward act, an ad read) but which is said again in a moment
    that passed takes that moment's date, link and words, the newest first."""
    if not facts or not moments:
        return facts
    failed = {str(m.get("fact_id")) for m in moments.get("rejected") or [] if m.get("kind") == "fact"}
    best: dict[str, dict] = {}
    for m in moments.get("usable") or []:
        fid = str(m.get("fact_id") or "")
        if m.get("kind") == "member" and fid in failed:
            if fid not in best or str(m.get("published") or "") > str(best[fid].get("published") or ""):
                best[fid] = m
    out = []
    for f in facts:
        m = best.get(str(f.get("fact_id")))
        if m:
            f = dict(f, url=m.get("url"), start=m.get("start"), published=m.get("published"),
                     quote=str(m.get("quote") or "").strip())
        out.append(f)
    return out


def load_moments(in_path: pathlib.Path | None, brand_id: str | None) -> dict | None:
    """``moments-<brand_id>.json`` beside the map, written by moment_check.py."""
    if in_path is None or not brand_id:
        return None
    p = in_path.parent / f"moments-{brand_id}.json"
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None   # unreadable is unchecked: main reports it like a missing file


_ANY_LINK = re.compile(r'href="([^"]+)"')
# "every", "always" and their kin claim a habit; outside a quotation the
# sentence must say how many videos show it
_PATTERN_WORD = re.compile(r"\b(every|always|each time|whenever|regularly|constantly|never misses)\b", re.I)
_COUNTED = re.compile(r"\b(?:\d+|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|several|"
                      r"most|half|all|dozens?) (?:of (?:his|her|their|them|the)\b|videos?\b|uploads?\b|"
                      r"times\b|clips?\b|episodes?\b|stunts?\b|streams?\b)", re.I)
_OVERCLAIM = re.compile(r"(\b100 ?%|\bfully verified\b|\bverified facts?\b|\bguaranteed accurate\b)", re.I)


# a link may open this many seconds before the quote's first word
LINK_LEAD_SECONDS = 3


def _spoken_at(cues: list[tuple[float, str]], hit: dict, quote: str) -> int:
    """The second the quote's first word is said: its cue's start, moved on
    by how far into a long cue the words sit (cues run up to ten seconds)."""
    idx = next((i for i, (t, _x) in enumerate(cues) if int(t) == int(hit["start"])), None)
    if idx is None:
        return int(hit["start"])
    text = _norm_words(cues[idx][1])
    first = " ".join(_norm_words(quote).split()[:3])
    at = text.find(first)
    if at <= 0 or not text:
        return int(hit["start"])
    end = cues[idx + 1][0] if idx + 1 < len(cues) else cues[idx][0] + 4.0
    return int(cues[idx][0] + (end - cues[idx][0]) * at / len(text))


def _quote_timing(moment: dict, quote: str, link_t: int) -> str | None:
    """Where a quote really starts in its moment's captions, and whether it
    stops with its sentence. None when both are fine or cannot be told."""
    cues = [(float(t), str(x)) for t, x in moment.get("cues") or []]
    if not cues or len(_norm_words(quote).split()) < 4:
        return None
    hit = locate(cues, quote, link_t)
    if hit.get("match") != "exact":
        return None
    begins = _spoken_at(cues, hit, quote)
    if begins - link_t > LINK_LEAD_SECONDS:
        return f"the link starts {begins - link_t} s before the quote; link &t={begins}s"
    q = quote.strip().rstrip("\"”")
    if q and q[-1] not in ".?!":
        # a caption tag ([Music]) between the quote and the next words is not punctuation
        nxt = re.sub(r"^(?:\s*\[[^\]]*\])+", "", _after_quote(cues, hit, quote)).lstrip()
        if nxt[:1].isalpha() and not re.match(r"^[,;:]", nxt):
            return "the quote stops mid-sentence; quote the whole sentence"
    return None


def _after_quote(cues: list[tuple[float, str]], hit: dict, quote: str) -> str:
    """The raw caption text right after the quote, found from the cue where
    the quote begins, so the captions' own full stop is seen and a repeat of
    the quote's last word elsewhere is not mistaken for its end."""
    idx = next((i for i, (t, _x) in enumerate(cues) if int(t) == int(hit["start"])), 0)
    raw = " ".join(x for _t, x in cues[idx:])
    # the normalised stream with a map back to the raw text
    norm, back = [], []
    tag = 0
    for i, ch in enumerate(raw):
        if ch == "[":
            tag += 1
        if tag:
            tag -= ch == "]"
            continue
        if ch.isalnum() or ch == "_":
            norm.append(ch.lower())
            back.append(i)
        elif ch.isspace() and norm and norm[-1] != " ":
            norm.append(" ")
            back.append(i)
    hay = "".join(norm)
    needle = _norm_words(quote)
    pos = hay.find(needle)
    while pos >= 0 and not ((pos == 0 or hay[pos - 1] == " ")
                            and (pos + len(needle) == len(hay) or hay[pos + len(needle)] == " ")):
        pos = hay.find(needle, pos + 1)
    if pos < 0 or pos + len(needle) >= len(back):
        return ""
    return raw[back[pos + len(needle) - 1] + 1:]


def _quotes_held_back(moment: dict, quote: str) -> str | None:
    """The quote repeats a ledger line the page may not use (five words in a
    row, or most of a short line), found in the window by moment_check."""
    held = moment.get("held_back") or {}
    line = _norm_words(str(held.get("quote") or "")).split()
    said = _norm_words(quote).split()
    if len(line) < 4 or not said:
        return None
    run = difflib.SequenceMatcher(None, line, said, autojunk=False).find_longest_match(
        0, len(line), 0, len(said)).size
    if run >= min(5, len(line)):
        return f"quotes a line the ledger holds back ({held.get('why')})"
    return None


def moment_problems(sections: list[tuple[str, str]], moments: dict) -> list[str]:
    """Every timed link on a concept card is a moment moment_check.py passed:
    the words checked, the date real, nothing awkward or rival within two
    minutes of it, the upload not a rival's, a plan still a plan."""
    usable = [(str(m.get("video_id")), int(m.get("start") or 0), m) for m in moments.get("usable") or []]
    rejected = [(str(m.get("video_id")), int(m.get("start") or 0), m) for m in moments.get("rejected") or []]
    out: list[str] = []
    for title, rest in sections:
        name = plain(title)[:60]
        if is_probe_quoted(title):
            # the lead quote is a lane window, not a ledger fact, so nothing
            # else checks where its link starts or whether it ends its sentence
            for block in _BLOCKQUOTE.findall(rest):
                raw_q = html.unescape(re.sub(r"<[^>]+>", " ", re.sub(r"<a\b[^>]*>.*?</a>", " ",
                                                                   block, flags=re.S))).strip()
                for url in quote_links(block):
                    vid, t = _video_and_time(url)
                    if not vid or t is None:
                        continue
                    ok = next((m for v, st, m in usable if v == vid and abs(st - t) <= 20), None)
                    why = _quote_timing(ok, raw_q, t) if ok is not None and raw_q else None
                    if why:
                        out.append(f"{why}: {raw_q[:40]!r} in {name}")
                    break
        for url in _ANY_LINK.findall(rest):
            vid, t = _video_and_time(url)
            if not vid or t is None:
                continue
            ok = next((m for v, st, m in usable if v == vid and abs(st - t) <= 20), None)
            if ok is not None:
                # the quote this link carries: the blockquote, or the list item's words
                block = rest[max(0, rest.find(url) - 600): rest.find(url) + 400]
                for q in _INLINE_QUOTE.findall(html.unescape(re.sub(r"<[^>]+>", " ", block))) or []:
                    why = _quote_timing(ok, q, t) or _quotes_held_back(ok, q)
                    if why:
                        out.append(f"{why}: {q[:40]!r} in {name}")
                        break
            if ok is None:
                bad = next((m for v, st, m in rejected if v == vid and abs(st - t) <= 20), None)
                why = "; ".join(bad.get("reasons") or []) if bad else "not among the checked moments"
                out.append(f"concept links a moment that did not pass moment_check ({why}): "
                           f"{vid}&t={t}s in {name}")
            elif ok.get("label") and ok["label"].lower() not in plain(rest).lower():
                out.append(f"concept uses a plan without its label {ok['label']!r}: {name}")
    return out


def check_page(md_text: str, facts: list[dict] | None, meta: dict,
               probe: dict | None = None, moments: dict | None = None) -> list[str]:
    """Contract problems with the deliverable, as one line each. Empty means
    the page is publishable. ``probe`` is the category probe's file when one
    exists: a precedent card quotes one of its windows, or fails.
    ``moments`` is moment_check.py's file: every concept link must be one of
    its usable moments, and no link anywhere may open a rival's upload."""
    problems: list[str] = []
    windows = probe_texts(probe)
    fm, body = parse_frontmatter(md_text)
    creator = fm.get("channel_name") or meta.get("channel_name") or ""
    kinds = section_kinds(md_text, meta)

    no_fit = not kinds["conn"]
    for key, label in (("creator", f"## About {creator or '<creator>'}"),
                       ("thesis", "## Verdict"),
                       ("brand", "## About <brand>")):
        if not kinds[key]:
            problems.append(f"missing section: {label}")
    if not kinds["caveat"]:
        problems.append("missing section: ## Creative guardrails, what the "
                        "integration must avoid is required even on a strong fit")
    for title, _rest in kinds["conn"]:
        if "confirm" in plain(title).lower():
            problems.append(f"a section asks the reader to confirm something; the page "
                            f"holds only confirmed facts, so drop it: {plain(title)[:60]}")
    m = _TO_CONFIRM.search(html.unescape(re.sub(r"<[^>]+>", " ", render_markdown(body))))
    if m:
        problems.append(f"the page asks the reader to confirm a fact with the creator's "
                        f"team ({m.group(0)!r}); leave an unconfirmed fact off the page instead")

    # "Who they are": the facts the map names must exist and be publishable,
    # and the list stays an introduction, not the ledger
    index = {str(f.get("fact_id")): f for f in (facts or [])}
    who = []
    for _title, rest in kinds["creator"]:
        who += who_lines(rest)[1]
    if facts is not None and kinds["creator"] and not who:
        problems.append("## About <creator> names no facts: add up to "
                        f"{WHO_PAGE_MAX} lines '- f012+f031: <line>'")
    if len(who) > WHO_PAGE_MAX:
        problems.append(f"## About <creator> names {len(who)} facts; at most {WHO_PAGE_MAX}")
    for ids, line in who:
        for fid in ids:
            if facts is None:
                break
            if fid not in index:
                problems.append(f"Who they are names {fid}, which is not in the ledger: "
                                f"{plain(line)[:50]}")
            else:
                reason = angle_ineligible_reason(index[fid], index)
                if reason and not story_ok(index[fid], index):
                    problems.append(f"Who they are names an ineligible fact ({fid}, {reason}): "
                                    f"{plain(line)[:50]}")
                elif reason and not _HISTORY_SPAN.search(plain(line)):
                    # a replaced or ended phase is history: the line gives when
                    problems.append(f"Who they are lists a past phase ({fid}, {reason}) without "
                                    f"its span (\"said from <Month YYYY> to <Month YYYY>\", \"until\", "
                                    f"\"used to\"): {plain(line)[:50]}")

    # every connection card must carry its evidence, and the evidence must be
    # the ledger's: a quote that matches no verified fact is the channel's
    # premise or the writer's memory, not a connection (a lead card can
    # otherwise quote an unrelated family fact to argue a format claim)
    thin = 0
    strong = 0
    flagged: set[str] = set()      # fact ids already reported as ineligible
    for title, rest in kinds["conn"]:
        name = plain(title)[:60]
        quotes = _BLOCKQUOTE.findall(rest)
        if not quotes:
            problems.append(f"connection carries no quote: {name}")
        elif not _TIMED_LINK.search(quotes[0]):
            problems.append(f"connection quote has no timestamped link: {name}")
        # A precedent card quotes a probe window, so it is exempt from ledger
        # membership. It is not exempt from the publication gate: a ledger
        # fact it happens to quote is judged like any other.
        is_precedent = is_probe_quoted(title)
        for quote in quotes if facts else []:
            fact = quote_matches_ledger(quote, facts)
            if fact is None:
                if not is_precedent:
                    problems.append(f"connection quote matches no ledger fact: {name}")
                elif probe is None:
                    pass                # no probe file: the caveat names the missing lane
                elif not windows:
                    problems.append(f"category-probe.json has no window text; the "
                                    f"precedent quote cannot be checked: {name}")
                else:
                    q = _norm_words(re.sub(r"<[^>]+>", " ",
                                           re.sub(r"<a\b[^>]*>.*?</a>", " ", quote, flags=re.S)))
                    hit = next((pw for pw in probe_windows(probe)
                                if q and q in _norm_words(str(pw.get("text") or ""))), None)
                    if hit is None and q:
                        # a whole sentence may start a cue before the window does
                        hit = next(({"published": m.get("published"), "text": q}
                                    for m in (moments or {}).get("usable") or []
                                    if m.get("kind") in ("window", "brand_window") and q in _norm_words(
                                        " ".join(str(c[1]) for c in m.get("cues") or []))), None)
                    if hit is None:
                        problems.append(f"precedent quote is not a window the brand-moments "
                                        f"lane returned (category-probe.json): {name}")
                    elif not is_recent({"last_seen": hit.get("published")}):
                        year = str(hit.get("published") or "")[:4]
                        if strength_of(title) == "strong":
                            problems.append(f"strong connection rests on a window from "
                                            f"{year or 'an unknown date'}, outside the last "
                                            f"{RECENT_MONTHS} months: {name}")
                        elif not year or year not in plain(rest):
                            problems.append(f"connection uses a window from {year or 'an unknown date'} "
                                            f"without stating the year: {name}")
                continue
            reason = angle_ineligible_reason(fact, index)
            if reason:
                flagged.add(str(fact.get("fact_id")))
                problems.append(f"connection quotes an ineligible fact "
                                f"({fact.get('fact_id')}, {reason}): {name}")
            cite = citation_problem(quote_text(quote), quote_links(quote),
                                    str(fact.get("quote") or ""), str(fact.get("url") or ""))
            if cite:
                problems.append(f"connection quote's link does not point at "
                                f"{fact.get('fact_id')} ({cite}): {name}")
            if not is_recent(fact):
                year = str(fact.get("last_seen") or fact.get("published") or "")[:4]
                if strength_of(title) == "strong":
                    problems.append(f"strong connection rests on a fact last said "
                                    f"{year or 'at an unknown date'}, outside the last "
                                    f"{RECENT_MONTHS} months ({fact.get('fact_id')}): {name}")
                elif year and year not in plain(rest):
                    problems.append(f"connection uses a fact last said {year} without "
                                    f"stating the year ({fact.get('fact_id')}): {name}")
        strength = strength_of(title)
        if strength is None:
            problems.append(f"connection heading has no strength tag "
                            f"(**strong** or **thin**): {name}")
        elif strength == "thin":
            thin += 1
        else:
            strong += 1
    if thin > MAX_THIN:
        problems.append(f"{thin} thin concepts; at most {MAX_THIN}. Fold the rest "
                        "into the Verdict")
    label = verdict_label(kinds["thesis"])
    want = "strong fit" if strong else "thin fit" if kinds["conn"] else "no fit"
    if kinds["thesis"] and label is None:
        problems.append(f"## Verdict does not open with its label: start it with "
                        f"'**{want.capitalize()}.**'")
    elif label and label != want:
        problems.append(f"## Verdict says {label!r} but the concepts make it {want!r}: "
                        "any strong concept is a strong fit, thin ones only a thin fit")
    problems += supporting_problems(kinds["conn"], facts, probe, "a supporting moment's", moments)
    problems += supporting_problems(kinds["channel"], facts, probe, "an On the channel already")

    # three concepts, three ways in: each names the kind of video it is, and
    # no two name the same one
    routes: dict[str, str] = {}
    for title, _rest in kinds["conn"]:
        r = concept_route(title)
        if not r:
            problems.append(f"concept heading names no route (the kind of video it is, "
                            f"as **<route>**): {plain(title)[:60]}")
        elif r in routes:
            problems.append(f"two concepts take the same route ({r!r}): {routes[r]} and "
                            f"{plain(title)[:40]}; each concept is a different way in")
        else:
            routes[r] = plain(title)[:40]
    if moments:
        problems += moment_problems(kinds["conn"], moments)
        # a fact said again in a clean moment is still usable: the story links there
        clean = {str(m.get("fact_id")) for m in moments.get("usable") or [] if m.get("fact_id")}
        failed = {str(m.get("fact_id")): "; ".join(m.get("reasons") or [])
                  for m in moments.get("rejected") or []
                  if m.get("kind") == "fact" and str(m.get("fact_id")) not in clean}
        by_link = {(str(m.get("video_id")), int(m.get("start") or 0)): m
                   for m in (moments.get("usable") or []) + (moments.get("rejected") or [])
                   if m.get("cues")}
        for _title, rest in kinds["creator"]:
            for ids, line in who_lines(rest)[1]:
                item = _who_item(ids, line, index) if facts else None
                spoken = next((f for f in (item or {}).get("facts") or []
                               if f.get("quote") and str(f.get("quote")) == item.get("quote")), None)
                if spoken:
                    vid, t = _video_and_time(str(spoken.get("url") or ""))
                    m = by_link.get((str(vid), int(t or 0))) if vid and t is not None else None
                    why_t = _quote_timing(m, str(spoken["quote"]), int(t)) if m else None
                    # the story shows the ledger's quote cut short, so only the link's timing counts
                    if why_t and why_t.startswith("the link starts"):
                        problems.append(f"story line {why_t}: {plain(line)[:50]}")
                for fid in ids:
                    why = failed.get(fid, "")
                    if any(k in why for k in ("ad read", "rival", "awkward", "word for word",
                                              "sponsored", "no transcript")):
                        problems.append(f"story line names {fid}, whose own moment failed "
                                        f"moment_check ({why}); leave it out: {plain(line)[:50]}")
        # a past partnership in the category is shown where it belongs ("done
        # this before", booking notes); everywhere else a rival's upload is
        # never the evidence for this brand
        rivals = set(str(v) for v in moments.get("rival_videos") or [])
        for _title, rest in kinds["conn"] + kinds["thesis"] + kinds["creator"]:
            for url in _ANY_LINK.findall(rest):
                vid, _t = _video_and_time(url)
                if vid and vid in rivals:
                    problems.append(f"the page links an upload a rival brand sponsored: {vid}")
    # a habit is counted, never assumed
    for title, rest in kinds["conn"] + kinds["thesis"]:
        prose = re.sub(r"<blockquote>.*?</blockquote>", " ", rest, flags=re.S)
        prose = _INLINE_QUOTE.sub(" ", html.unescape(re.sub(r"<[^>]+>", " ", prose)))
        for sentence in re.split(r"(?<=[.!?])\s+", prose):
            if _PATTERN_WORD.search(sentence) and not _COUNTED.search(sentence) \
                    and not re.match(r"\s*(Do|Don[’']t|Do not|Sample)\b", sentence):
                problems.append(f"{_PATTERN_WORD.search(sentence).group(0)!r} without a count of the "
                                f"videos that show it: {sentence.strip()[:80]}")
    m = _OVERCLAIM.search(html.unescape(re.sub(r"<[^>]+>", " ", render_markdown(body))))
    if m:
        problems.append(f"the page claims certainty ({m.group(0)!r}); say what was checked instead")

    # the bans that survive the sample-read exception
    for m in _MONEY.finditer(html.unescape(re.sub(r"<[^>]+>", " ", body))):
        problems.append(f"price, cost or rate language on the page: "
                        f"{m.group(0).strip()!r}")
        break
    # the cards are not the only place a quote can sit: the About, Thesis and
    # caveat sections are on the brand's page too, quoted or inline
    for f, reason in ineligible_on_page(re.sub(r"\]\([^)]*\)", "]", body),
                                        facts, index, flagged):
        problems.append(f"the page quotes an ineligible fact ({f.get('fact_id')}, "
                        f"{reason}): {str(f.get('claim'))[:50]}")

    # Only angle-eligible facts may be selected for the brand-facing summary.
    for f in (facts or []):
        reason = angle_ineligible_reason(f, index)
        # the child and money backstops only keep a fact off the page; a
        # ledger built before them can still carry such a pick, and the
        # writer cannot change the ledger, so they are not the writer's fault
        if reason and f.get("selected") and not reason.startswith("names "):
            problems.append(f"selected fact is not publishable ({reason}): "
                            f"{str(f.get('claim'))[:50]}")
    # the merge pass owns this rule; this end is the backstop, and it re-derives
    # corroboration from the evidence link rather than trusting `confidence`
    for f in (facts or []):
        if f.get("selected") and unverified_bio(f, index):
            problems.append(f"selected fact the creator only wrote about themselves, "
                            f"uncorroborated: {str(f.get('claim'))[:50]}")
        if unverified_bio(f, index) and tier_of(f) in ("clinical", "children", "location"):
            problems.append(f"uncorroborated bio fact at a sensitive tier is in the "
                            f"ledger and should have been dropped: {str(f.get('claim'))[:50]}")
    if no_fit and not kinds["thesis"]:
        problems = [p for p in problems if not p.startswith("missing section: ## Verdict")]
    return problems


# --------------------------------------------------------------------------- #
# --brief: the creator-friendly brief, the second deliverable of a CONNECT run
# --------------------------------------------------------------------------- #
# Written for a third audience, the creator. The connections page argues the
# fit to the account manager; this file tells the creator what the brand wants
# said and which of their own moments already say it. Same evidence rules,
# second person, and nothing that was written for the brand's eyes.
BRIEF_SCHEMA = "tl-creator-brief/v1"
BRIEF_INPUT_SCHEMA = "tl-creator-brief-input/v1"
# the six sections, in the order the brand-side template fixes; the first is
# matched on its prefix because it names the brand
BRIEF_SECTIONS = (
    ("who", "Who is <brand>", lambda t: t.startswith("who is")),
    ("ask", "The creative ask", lambda t: t == "the creative ask"),
    ("points", "Key talking points", lambda t: t == "key talking points"),
    ("requirements", "Requirements", lambda t: t == "requirements"),
    ("dont", "Don't do", lambda t: t in ("don't do", "do not do", "don'ts", "dont do")),
    ("approval", "Creative approval process",
     lambda t: t == "creative approval process"),
)
NO_MOMENT = re.compile(r"no natural moment", re.I)
# vocabulary that exists for the brand's or the AM's eyes only
_BRIEF_BANNED = [
    r"\*\*strong\*\*", r"\*\*thin\*\*", r"\bthin fit\b", r"\bprecedent\b",
    r"sponsorship pattern", r"ad-read sample", r"\bad read sample\b", r"\[web",
    r"\[social", r"\bledger\b", r"-facts\.jsonl", r"connections-\d", r"\.jsonl\b",
    r"channel_id", r"brand_id", r"Where this could go wrong", r"Good to know when booking",
    r"Creative guardrails", r"\bprobe\b",
    r"\bunconfirmed\b", r"honesty strip", r"connections page", r"connection map",
]
_FACT_ID = re.compile(r"(?<![\w-])f\d{1,4}(?![\w-])")
# a bare 5-7 digit number outside a link is a platform id
_PLATFORM_ID = re.compile(r"(?<![\w=&?/.:-])\d{5,7}(?![\w-])")
_CTA = re.compile(r"\b(download (?:it|now|the app)|link in (?:the )?description|use code"
                  r"|sign up|click (?:the|here|below))\b", re.I)
# the creator file builds the brand up; it never sets it against another
# product, even one the creator plays
_AGAINST = re.compile(r"\b(instead of|put (?:\w+ )?down|better than|ditch(?:ing)?"
                      r"|swap(?:ping)? out|rather than (?:playing|using|opening))\b", re.I)


def md_quote_blocks(md: str) -> list[tuple[str, list[str]]]:
    """``(normalised text, link targets)`` of every `>` block: the quoted
    words with attribution links dropped, and the links kept apart so each
    citation can be checked against the passage it cites."""
    out = []
    for m in re.finditer(r"((?:^> ?.*\n?)+)", md, re.M):
        block = re.sub(r"^> ?", "", m.group(1), flags=re.M)
        text = _norm_words(re.sub(r"\[[^\]]*\]\([^)]*\)", " ", block))
        if text:
            out.append((text, quote_links(block)))
    return out


def md_precedent_quotes(md: str) -> set[str]:
    """The normalised text of every `>` block under a category-precedent
    heading of the map: the probe windows the map argued, which are the
    creator's own words at a timestamp even though no ledger fact holds them."""
    out: set[str] = set()
    for section in re.split(r"(?m)^## ", md)[1:]:
        heading = section.splitlines()[0] if section else ""
        if "precedent" in heading.lower() or "brand moment" in heading.lower():
            out.update(text for text, _links in md_quote_blocks(section))
    return out


def md_blockquotes(md: str) -> list[str]:
    """The normalised text of every `>` block, attribution links dropped."""
    return [text for text, _links in md_quote_blocks(md)]


def brief_sections(body: str) -> tuple[str, dict[str, str], list[str], list[str]]:
    """``(intro, {key: section text}, order of keys found, unknown headings)``."""
    parts = re.split(r"(?m)^## ", body)
    intro, found, order, unknown = parts[0], {}, [], []
    for part in parts[1:]:
        heading, _, rest = part.partition("\n")
        t = heading.strip().lower().replace("’", "'").rstrip("?").strip()
        for key, _label, match in BRIEF_SECTIONS:
            if match(t):
                found[key] = rest
                order.append(key)
                break
        else:
            unknown.append(heading.strip())
    return intro, found, order, unknown


ALSO = re.compile(r"(?i)^also from\b")
_FROM_BRIEF = re.compile(r"(?mi)^\*\*from [^*\n]*brief:?\*\*:?")
_STOP = set("""a an and are as at be been but by can do for from had has have her his i if in
into is it its just me my no not of on or our she so than that the their them then there
they this to too up us was we were what when which who will with would you your yours
youre ive im dont""".split())


def split_brand_lines(sub: str) -> tuple[str, str]:
    """``(the brand's lines, our words)`` of one talking point: everything from
    the 'From <brand>'s brief:' label down is the brand's; quotes are neither."""
    m = _FROM_BRIEF.search(sub)
    brand_part = sub[m.end():] if m else ""
    ours = sub[:m.start()] if m else sub
    ours = re.sub(r"(?m)^>.*$", " ", ours)
    return brand_part, ours


_FIRST_PERSON = re.compile(r"\b(i|i'm|im|i've|ive|i'd|i'll|me|my|mine|myself|we|we're|our)\b", re.I)


def _content_words(text: str) -> set[str]:
    words = _norm_words(re.sub(r"\]\([^)]*\)", "]", text or "")).split()
    return {w for w in words if len(w) > 2 and w not in _STOP}


_FOR_YOU = re.compile(r"(?s)<!--\s*for-you\s*-->(.*?)<!--\s*/for-you\s*-->")
_FOR_YOU_HEAD = re.compile(r"^\s*\*\*\s*for you:\s*(.+?)\s*\*\*\s*$", re.I)
MIRROR_CREATIVE_CAP = 2   # gem-led points that follow none of the brand's lines


def mirror_mode(inp: dict | None) -> bool:
    """The brand sent its own brief: the creator brief is that document, in
    its headings, order and words, with the creator's own version of each
    talking point written in beneath it. Without one, the six sections."""
    return bool(inp and inp.get("supplied") and str(inp.get("brand_brief") or "").strip())


def for_you_parts(block: str) -> tuple[str, str]:
    """``(heading, our words)`` of one For you block; quotes are neither."""
    lines = block.strip().splitlines()
    m = _FOR_YOU_HEAD.match(lines[0]) if lines else None
    heading = m.group(1).strip() if m else ""
    rest = "\n".join(lines[1:] if m else lines)
    return heading, heading + "\n" + re.sub(r"(?m)^>.*$", " ", rest)


def check_mirror(body: str, facts: list[dict] | None, map_md: str, inp: dict,
                 corpus_cues: dict[str, list] | None = None,
                 brand: str = "", past_reads: list | None = None) -> list[str]:
    """Contract problems with a creator brief that mirrors the brand's own:
    their document word for word in its order, and a For you block, built on
    a gem of the creator's, under the talking points a gem backs."""
    problems: list[str] = []
    blocks = _FOR_YOU.findall(body)
    rest = _FOR_YOU.sub(" ", body)
    if re.search(r"<!--\s*/?\s*for-you", rest):
        problems.append("a <!-- for-you --> marker without its closing <!-- /for-you -->")
    # the brand's document, word for word and in its order; formatting (a
    # heading mark, a bullet) may be added, a word may not
    want = _norm_words(str(inp.get("brand_brief"))).split()
    got = _norm_words(rest).split()
    if got != want:
        i = next((k for k, (x, y) in enumerate(zip(got, want)) if x != y),
                 min(len(got), len(want)))
        near = " ".join(want[max(0, i - 4):i + 6]) or " ".join(got[max(0, i - 4):i + 6])
        problems.append(f"the brand's brief is not kept word for word in its order; it "
                        f"changes near: '{near}'")
    if not blocks:
        problems.append("no For you block under any of the brand's talking points; write "
                        "the creator's version of each point a gem of theirs backs")
    supplied_norm = [_norm_words(tp) for tp in inp.get("talking_points", []) if tp]
    map_blocks = md_quote_blocks(map_md)
    precedent_blocks = md_precedent_quotes(map_md)
    index = {str(f.get("fact_id")): f for f in (facts or [])}
    flagged: set[str] = set()
    personal: list[dict] = []
    ours_all = ""
    for blk in blocks:
        heading, ours = for_you_parts(blk)
        name = heading[:60] or "(untitled)"
        if not heading:
            problems.append("a For you block does not open with **For you: <the point>**")
        elif _norm_words(heading) in supplied_norm:
            problems.append(f"the For you heading is the brand's own line; write the "
                            f"creator's version of it: {name}")
        pp, carried = point_problems(blk, ours, name, facts, index, map_blocks,
                                     precedent_blocks, flagged)
        problems += pp
        if carried is not None:
            personal.append(carried)
            pr = prior_read_problem(carried, brand, corpus_cues, name, past_reads)
            if pr:
                problems.append(pr)
        ours_all += "\n" + ours
    problems += personal_coverage(blocks, personal, facts,
                                  cap=len(supplied_norm) + MIRROR_CREATIVE_CAP)
    # the bans hold on OUR words; the brand's document is theirs to phrase
    ours_plain = re.sub(r"\]\([^)]*\)", "]", ours_all)
    for pat in _BRIEF_BANNED:
        m = re.search(pat, ours_all, re.I)
        if m:
            problems.append(f"brand-side material on the creator page: {m.group(0)!r}")
    for rx, label in ((_FACT_ID, "a fact id on the page"),
                      (_PLATFORM_ID, "a platform id on the page")):
        m = rx.search(ours_plain)
        if m:
            problems.append(f"{label}: {m.group(0)}")
    for rx, label in ((_MONEY, "price, cost or rate language"),
                      (_CTA, "CTA wording on the page (the brand owns the CTA)"),
                      (_AGAINST, "sets the brand against something else")):
        m = rx.search(ours_plain)
        if m:
            problems.append(f"{label}: {m.group(0).strip()!r}")
    no_links = re.sub(r"\]\([^)]*\)", "]", body)
    for f, reason in ineligible_on_page(no_links, facts, index, flagged):
        label = ("withheld-tier quote" if tier_of(f) in WITHHELD
                 else "quote of an ineligible fact")
        problems.append(f"{label} on the page ({reason}): {str(f.get('claim'))[:50]}")
    return problems


PRIOR_READ_SPAN = 45   # seconds either side of a moment the brand's name must not sit


def load_corpus_cues(in_path: pathlib.Path | None) -> dict[str, list] | None:
    """``corpus.jsonl.gz`` beside the map: each video's timed transcript cues,
    by video id. None when the run left no corpus there."""
    if in_path is None:
        return None
    p = in_path.parent / "corpus.jsonl.gz"
    if not p.is_file():
        return None
    out: dict[str, list] = {}
    try:
        with gzip.open(p, "rt", encoding="utf-8") as fh:
            for line in fh:
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                vid = str(d.get("id") or "").rsplit(":", 1)[-1]
                if vid:
                    out[vid] = d.get("cues") or []
    except OSError:
        return None
    return out


def past_read_spots(map_path: pathlib.Path) -> list[tuple[str, float, float]]:
    """``(video id, read start, read end)`` of the creator's own past reads
    for the brand: ``this_channel_reads`` in ``brand-tl.json`` beside the map.
    A read with no end is its start; a (0, 0) span has no position."""
    try:
        data = json.loads((map_path.parent / "brand-tl.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    rows = data.get("this_channel_reads") if isinstance(data, dict) else None
    spots = []
    for r in rows or []:
        if not (isinstance(r, dict) and r.get("video_id")
                and isinstance(r.get("start"), (int, float))):
            continue
        start = float(r["start"])
        end = float(r["end"]) if isinstance(r.get("end"), (int, float)) else start
        if start > 0 or end > 0:
            spots.append((str(r["video_id"]), start, max(start, end)))
    return spots


def prior_read_problem(fact: dict, brand: str, cues_by_video: dict[str, list] | None,
                       name: str, past_reads: list | None = None) -> str | None:
    """A re-book never repeats the last read: a moment said inside the
    creator's own earlier read for this brand is the ad talking, not a gem.
    The moment sits within PRIOR_READ_SPAN seconds of one of the creator's
    past reads for the brand (``past_reads``), or the video is one the brand
    sponsored (its transcript says so) with the brand's name that close."""
    vid, t = _video_and_time(str(fact.get("url") or ""))
    if vid and t is not None and any(v == vid and s - PRIOR_READ_SPAN <= t <= e + PRIOR_READ_SPAN
                                     for v, s, e in past_reads or []):
        return (f"talking point rests on a moment from inside the creator's own {brand} read "
                f"({vid} at {t // 60}:{t % 60:02d}); a re-book never repeats the last read, "
                f"build it on a gem from outside it: {name}")
    if not cues_by_video or not brand:
        return None
    cues = cues_by_video.get(vid or "")
    if not cues or t is None:
        return None
    b = r"\b" + r"\s+".join(re.escape(w) for w in brand.lower().split()) + r"\b"
    text = " ".join(str(c[1]) for c in cues if len(c) > 1).lower()
    sponsored = re.search(
        r"(?:sponsored by|thanks? (?:you )?to|brought to you by|partner(?:ed|ing)? with"
        r"|in partnership with)\s+(?:\w+\s+){0,3}?" + b + "|" + b
        + r"\s+(?:for sponsoring|is sponsoring|sponsored)", text)
    if not sponsored:
        return None
    near = [c for c in cues if len(c) > 1 and abs(float(c[0]) - t) <= PRIOR_READ_SPAN]
    if not any(re.search(b, str(c[1]).lower()) for c in near):
        return None
    return (f"talking point rests on a moment from inside the creator's own {brand} read "
            f"({vid} at {t // 60}:{t % 60:02d}); a re-book never repeats the last read, "
            f"build it on a gem from outside it: {name}")


def point_problems(sub: str, ours: str, name: str, facts: list[dict] | None,
                   index: dict, map_blocks: list, precedent_blocks: list,
                   flagged: set[str]) -> tuple[list[str], dict | None]:
    """One talking point written for the creator: the problems with it, and
    the moment of their own it is built on (None when it has none). The same
    rules hold in both layouts."""
    problems: list[str] = []
    qs = md_quote_blocks(sub)
    if not qs:
        problems.append(f"talking point is built on no moment of the creator's own "
                        f"(no quote): {name}")
        return problems, None
    if not re.search(r"\]\(https?://[^)]*[?&]t=\d", sub):
        problems.append(f"talking point quote has no timestamped link: {name}")
    carried = None
    for q, links in qs:
        fact = quote_matches_ledger(q, facts)
        in_map = next(((mq, ml) for mq, ml in map_blocks if q in mq or mq in q), None)
        if fact is None and in_map is None:
            problems.append(f"quote is neither a ledger fact nor one the connections "
                            f"map argued: {name}")
        if fact is not None:
            reason = angle_ineligible_reason(fact, index)
            if reason:
                flagged.add(str(fact.get("fact_id")))
                label = ("a withheld-tier fact" if reason.startswith("withheld tier")
                         else "an ineligible fact")
                problems.append(f"quote uses {label} ({reason}): {name}")
            elif not is_recent(fact):
                year = str(fact.get("last_seen") or fact.get("published") or "")[:4]
                when = year or "at an unknown date"
                problems.append(f"talking point rests on a fact last said {when}, "
                                f"outside the last {RECENT_MONTHS} months "
                                f"({fact.get('fact_id')}): {name}")
            cite = citation_problem(q, links, str(fact.get("quote") or ""),
                                    str(fact.get("url") or ""))
            if str(fact.get("confidence")) == "confirmed":
                carried = carried or fact
        elif in_map is not None:
            # a map-only quote is cited where the map cites it
            mq, ml = in_map
            timed = [u for u in ml if _video_and_time(u)[1] is not None]
            cite = citation_problem(q, links, mq, timed[0] if timed else "")
            # a precedent window the map argued, in the creator's own first
            # person and at a timestamp, is their moment as much as a
            # ledger fact is: refusing it as "a topic the channel covered"
            # was what turned a host's own bank story away
            if (timed and mq in precedent_blocks and q in mq
                    and _FIRST_PERSON.search(mq)):
                carried = carried or {"fact_id": f"probe:{timed[0]}", "claim": "",
                                      "quote": mq, "url": timed[0],
                                      "confidence": "confirmed", "provenance": "probe"}
        else:
            cite = None
        if cite:
            problems.append(f"the quote's link does not point at the moment it "
                            f"quotes ({cite}): {name}")
    if carried is None:
        problems.append(f"talking point rests on a topic the channel covered, not a "
                        f"moment of the creator's own: {name}")
        return problems, None
    moment = _content_words(f"{carried.get('quote')} {carried.get('claim')}")
    body_words = _content_words(ours.partition("\n")[2])
    # the heading may name the moment, but the body has to use it too
    if len(_content_words(ours) & moment) < 2 or not body_words & moment:
        problems.append(f"talking point quotes a moment but is not built from it; say what "
                        f"the creator does with it on camera: {name}")
    if len(_content_words(ours)) < 15:
        problems.append(f"talking point is too thin to tell the creator what to say: {name}")
    return problems, carried


def other_creator_names(map_path: pathlib.Path, creator: str | None) -> list[str]:
    """Channel names in ``brand-tl.json`` beside the map, the creator's own
    excepted: the brief never names another creator."""
    try:
        data = json.loads((map_path.parent / "brand-tl.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    names = set()
    for key in ("reads", "top_channels"):
        for row in data.get(key) or [] if isinstance(data, dict) else []:
            if isinstance(row, dict):
                n = str(row.get("channel_name") or row.get("name") or "").strip()
                if len(n) >= 4 and n.lower() != str(creator or "").lower():
                    names.add(n)
    return sorted(names)


def check_brief(md_text: str, facts: list[dict] | None, map_md: str,
                inp: dict | None,
                corpus_cues: dict[str, list] | None = None,
                other_creators: list[str] | None = None,
                past_reads: list | None = None) -> list[str]:
    """Contract problems with the creator brief, one line each. Empty means
    it can be sent."""
    problems: list[str] = []
    fm, body = parse_frontmatter(md_text)
    brand = fm.get("brand_name") or ""
    if fm.get("schema") != BRIEF_SCHEMA:
        problems.append(f"frontmatter schema is not {BRIEF_SCHEMA}")
    for key in ("channel_name", "brand_name"):
        if not fm.get(key):
            problems.append(f"frontmatter lacks {key}")
    for key in ("channel_id", "brand_id", "facts_file", "connections_file"):
        if key in fm:
            problems.append(f"frontmatter carries a platform internal: {key}")
    if inp is not None and inp.get("schema") != BRIEF_INPUT_SCHEMA:
        problems.append(f"input file schema is not {BRIEF_INPUT_SCHEMA}")
    supplied = bool(inp and inp.get("supplied"))
    if str(fm.get("talking_points_supplied", "")).lower() not in ("true", "false"):
        problems.append("frontmatter lacks talking_points_supplied: true|false")
    elif (fm["talking_points_supplied"].lower() == "true") != supplied:
        problems.append(f"talking_points_supplied says {fm['talking_points_supplied']} "
                        f"but the input file says {supplied}")

    if mirror_mode(inp):
        # the brand's own document is theirs word for word; our For you blocks are not
        ours = " ".join(_FOR_YOU.findall(body))
        for other in other_creators or []:
            if re.search(r"(?<!\w)" + re.escape(other) + r"(?!\w)", ours, re.I):
                problems.append(f"names another creator: {other!r}")
        return problems + check_mirror(body, facts, map_md, inp, corpus_cues,
                                       brand, past_reads)

    intro, found, order, unknown = brief_sections(body)
    expected = [k for k, _l, _m in BRIEF_SECTIONS]
    for key, label, _m in BRIEF_SECTIONS:
        if key not in found:
            problems.append(f"missing section: ## {label.replace('<brand>', brand or '<brand>')}")
    if order != [k for k in expected if k in found]:
        problems.append("sections out of order; the template fixes: "
                        + ", ".join(label for _key, label, _match in BRIEF_SECTIONS))
    for h in unknown:
        problems.append(f"a section the template does not have: ## {h[:50]}")
    if brand and "who" in found and not re.search(
            r"(?mi)^## who is " + re.escape(brand) + r"\s*\??\s*$", body):
        problems.append(f"the first section does not name the brand: ## Who is {brand}")

    # key talking points: each is written for this creator, built on a moment
    # of their own, with the brand's line it covers kept verbatim beneath it;
    # what no moment carries waits in one closing "Also from <brand>" list
    map_blocks = md_quote_blocks(map_md)
    precedent_blocks = md_precedent_quotes(map_md)
    index = {str(f.get("fact_id")): f for f in (facts or [])}
    flagged: set[str] = set()          # fact ids already reported as ineligible
    points = found.get("points", "")
    subs = re.split(r"(?m)^### ", points)
    if len(subs) < 2:
        problems.append("no ### talking point under ## Key talking points")
    supplied_norm = [_norm_words(tp) for tp in (inp or {}).get("talking_points", []) if tp]
    # a creative point is one a gem of the creator's carries and none of the
    # brand's lines do: it stands under the brand's promoting line instead
    promoting_norm = _norm_words(str((inp or {}).get("promoting") or ""))
    anchors = supplied_norm + ([promoting_norm] if promoting_norm else [])
    personal: list[dict] = []          # the ledger fact each point is built on
    points_subs: list[str] = []        # the creator's talking points, the "also" list apart
    in_personal = ""                   # brand text the creator's points carry
    for sub in subs[1:]:
        heading = sub.splitlines()[0].strip() if sub.strip() else ""
        name = heading[:60] or "(untitled)"
        if ALSO.match(heading):
            if not supplied and not NO_MOMENT.search(sub):
                problems.append(f"'Also from {brand or '<brand>'}' on a brief the brand sent no "
                                f"lines for; build every point on a gem instead")
            if md_blockquotes(sub):
                problems.append(f"a quote in the closing list; build a talking point on it: {name}")
            continue
        points_subs.append(sub)
        brand_part, ours = split_brand_lines(sub)
        if not supplied and _FROM_BRIEF.search(sub):
            problems.append(f"'From {brand or '<brand>'}'s brief:' on a brief the brand sent no "
                            f"lines for; there is nothing of theirs to quote: {name}")
        in_personal += " " + brand_part
        if _norm_words(heading) in supplied_norm:
            problems.append(f"the heading is the brand's own line; write the creator's "
                            f"talking point in its place and keep the line under "
                            f"'From {brand or '<brand>'}'s brief': {name}")
        if supplied and not any(tp and tp in _norm_words(brand_part) for tp in anchors):
            problems.append(f"talking point shows none of the brand's lines verbatim under "
                            f"'From {brand or '<brand>'}'s brief:' (a creative point the "
                            f"brand did not write carries its promoting line): {name}")
        pp, carried = point_problems(sub, ours, name, facts, index, map_blocks,
                                     precedent_blocks, flagged)
        problems += pp
        if carried is not None:
            personal.append(carried)
            pr = prior_read_problem(carried, brand, corpus_cues, name, past_reads)
            if pr:
                problems.append(pr)
    problems += personal_coverage(points_subs, personal, facts)
    if supplied and points_subs:
        pts = [tp for tp in supplied_norm if tp in _norm_words(points)]
        carried_n = sum(1 for tp in pts if tp in _norm_words(in_personal))
        if pts and carried_n * 2 < len(pts) and len(usable_moments(facts)) >= 3:
            problems.append(f"only {carried_n} of the brand's {len(pts)} talking-point lines "
                            f"sit inside a talking point written for the creator; move more "
                            f"out of the closing list and build on them")
    elif not points_subs and not NO_MOMENT.search(points):
        problems.append("no talking point written for the creator, and the closing list "
                        "does not say 'no natural moment'")

    # the brand's own lines, verbatim and all present: a talking point under
    # Key talking points, a mandatory, a don't or an approval step in its own
    # section, each once, so a pasted full brief is sorted rather than repeated
    if inp:
        placed = _norm_words(" ".join(found.get(k, "") for k in
                                      ("points", "requirements", "dont", "approval")))
        for tp in inp.get("talking_points", []):
            if _norm_words(tp) not in placed:
                problems.append(f"supplied talking point missing or reworded: {tp[:50]!r}")
        if inp.get("promoting") and _norm_words(inp["promoting"]) not in _norm_words(found.get("ask", "")):
            problems.append("the brand's 'promoting' line is not in The creative ask verbatim")
    for key, label in (("who", "Who is the brand"), ("ask", "The creative ask"),
                       ("requirements", "Requirements"), ("dont", "Don't do"),
                       ("approval", "Creative approval process")):
        if key in found and not found[key].strip():
            problems.append(f"empty section: {label}")

    # nothing written for the brand's or the AM's eyes, and nothing that is copy
    no_links = re.sub(r"\]\([^)]*\)", "]", body)
    for pat in _BRIEF_BANNED:
        m = re.search(pat, body, re.I)
        if m:
            problems.append(f"brand-side material on the creator page: {m.group(0)!r}")
    for other in other_creators or []:
        if re.search(r"(?<!\w)" + re.escape(other) + r"(?!\w)", no_links, re.I):
            problems.append(f"names another creator: {other!r}")
    m = _FACT_ID.search(no_links)
    if m:
        problems.append(f"a fact id on the page: {m.group(0)}")
    m = _PLATFORM_ID.search(no_links)
    if m:
        problems.append(f"a platform id on the page: {m.group(0)}")
    m = _MONEY.search(body)
    if m:
        problems.append(f"price, cost or rate language: {m.group(0).strip()!r}")
    # the framing bans are on OUR words: the brand's own lines are theirs to
    # phrase, so every supplied line is cut out before these two run
    ours = no_links
    for line in supplied_lines(inp):
        ours = re.sub(r"\s+".join(re.escape(w) for w in line.split()), " ", ours, flags=re.I)
    m = _CTA.search(ours)
    if m:
        problems.append(f"CTA wording on the page (the brand owns the CTA): {m.group(0)!r}")
    m = _AGAINST.search(ours)
    if m:
        problems.append(f"sets the brand against something else: {m.group(0)!r}")
    # The template bans ineligible material in every section, not only under
    # the talking points: every other quote on the page goes through the same
    # gate, and then the whole page is scanned for a ledger quote written
    # inline without the `>`.
    elsewhere = intro + "".join(found[k] for k in found if k != "points")
    for q, _links in md_quote_blocks(elsewhere):
        fact = quote_matches_ledger(q, facts)
        reason = fact and angle_ineligible_reason(fact, index)
        if reason:
            flagged.add(str(fact.get("fact_id")))
            problems.append(f"quote outside the talking points uses an ineligible fact "
                            f"({reason}): {str(fact.get('claim'))[:50]}")
    for f, reason in ineligible_on_page(no_links, facts, index, flagged):
        label = ("withheld-tier quote" if tier_of(f) in WITHHELD
                 else "quote of an ineligible fact")
        problems.append(f"{label} on the page ({reason}): {str(f.get('claim'))[:50]}")
    return problems


def usable_moments(facts: list[dict] | None) -> list[dict]:
    """Confirmed, unwithheld moments of the creator's own, said on camera: what
    a talking point can be built on without a human opting anything in."""
    index = {str(f.get("fact_id")): f for f in (facts or [])}
    return [f for f in facts or []
            if str(f.get("confidence")) == "confirmed" and tier_of(f) == "none"
            and f.get("quote") and re.search(r"[?&]t=\d", str(f.get("url") or ""))
            and angle_ineligible_reason(f, index) is None
            and str(f.get("provenance") or "transcript") == "transcript"
            # a child the merge left at tier none is still not an angle to push
            and not tier_hint.names_child(f.get("claim"), f.get("quote"))]


def personal_coverage(subs: list[str], personal: list[dict],
                      facts: list[dict] | None, cap: int | None = None) -> list[str]:
    """The brief is personal or it is the brand's brief with a name on it: at
    least four talking points written for the creator (fewer only when the
    ledger holds fewer confirmed moments), each on a moment of its own."""
    problems: list[str] = []
    ids = [str(f.get("fact_id") or id(f)) for f in personal]
    if len(set(ids)) < len(ids):
        problems.append("the same moment of the creator's carries two talking points; "
                        "give each point its own")
    usable = usable_moments(facts)
    need = min(4, len({str(f.get("fact_id")) for f in usable}))
    if cap is not None:
        need = min(need, cap)
    if len(set(ids)) >= need:
        return problems
    used = set(ids)
    spare = sorted((f for f in usable if str(f.get("fact_id")) not in used),
                   key=lambda f: (not f.get("selected"), -(f.get("recurrence") or 0)))
    # one per life domain first, so the hint shows the breadth of the ledger
    firsts, domains = [], set()
    for f in spare:
        if f.get("domain") not in domains:
            firsts.append(f)
            domains.add(f.get("domain"))
    hints = (firsts + [f for f in spare if f not in firsts])[:8]
    problems.append(
        f"only {len(set(ids))} talking points are built on a moment of the creator's own; "
        f"at least {need} should, and the ledger has confirmed moments unused, for example: "
        + "; ".join(f"{h.get('claim')} ({h.get('domain')})" for h in hints))
    return problems


def supplied_lines(inp: dict | None) -> list[str]:
    """Every line the brand supplied, verbatim: the text that is theirs."""
    if not inp:
        return []
    lines = list(inp.get("talking_points") or [])
    if inp.get("promoting"):
        lines.append(str(inp["promoting"]))
    return [ln for ln in lines if ln.strip()]


def brief_slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-") or "x"


def default_brief_out(in_path: pathlib.Path, facts_path: pathlib.Path | None,
                      fm: dict) -> pathlib.Path:
    """Named by names, never ids: this file is an attachment."""
    name = (f"{brief_slug(fm.get('brand_name'))}-creator-brief-"
            f"{brief_slug(fm.get('channel_name'))}.html")
    return (facts_path.parent if facts_path is not None else in_path.parent) / name


_BRIEF_CSS = """<style>
.brief h2{margin-top:2.2rem}
.brief h3{margin:1.6rem 0 .4rem;font-size:1.05rem}
.brief blockquote{border-left:3px solid var(--accent);margin:.6rem 0;padding:.2rem 0 .2rem 1rem;color:var(--quote)}
.brief .note{font-size:.9em;color:var(--ink-2)}
.brief .for-you{border:1px solid var(--accent);border-radius:8px;margin:.8rem 0 1.2rem;padding:.2rem 1rem .6rem}
.brief .for-you .fy-label{font-size:.75rem;letter-spacing:.06em;text-transform:uppercase;color:var(--accent);margin:.6rem 0 0}
.brief .for-you h4{margin:.2rem 0 .4rem;font-size:1rem}
</style>"""


def render_brief(md_text: str, inp: dict | None) -> tuple[str, str, str]:
    """``(title, page, fragment)`` for the creator brief."""
    fm, body = parse_frontmatter(md_text)
    creator = fm.get("channel_name") or "Creator"
    brand = fm.get("brand_name") or "Brand"
    title = f"{brand} creator brief for {creator}"
    chips = [f"prepared {time.strftime('%Y-%m-%d')}"]
    if not (inp and inp.get("supplied")):
        chips.append("built from the creator's own material; no brand talking points supplied")
    header_extra = ('<ul class="meta">'
                    + "".join(f"<li>{html.escape(c)}</li>" for c in chips) + "</ul>")
    if mirror_mode(inp):
        # the brand's document as they wrote it, the creator's versions of its
        # points set in beneath the lines they belong to
        parts = _FOR_YOU.split(body)
        inner = ""
        for i, part in enumerate(parts):
            if i % 2 == 0:
                inner += render_markdown(part)
                continue
            heading, _ours = for_you_parts(part)
            rest = "\n".join(part.strip().splitlines()[1:])
            inner += ('<div class="for-you"><p class="fy-label">For you</p>'
                      f"<h4>{inline(html.escape(heading, quote=False))}</h4>"
                      + render_markdown(rest) + "</div>")
    else:
        inner = render_markdown(body)
    body_html = _BRIEF_CSS + '<div class="brief">' + inner + "</div>"
    eyebrow = "creator brief"
    return (title, page_html(title, eyebrow, header_extra, body_html),
            page_fragment(title, eyebrow, header_extra, body_html))


def funnel(**fields) -> None:
    """One machine-parseable stage line for debugging (stderr)."""
    print("FUNNEL " + " ".join(f"{k}={v}" for k, v in fields.items()),
          file=sys.stderr)


def main() -> None:
    t0 = time.monotonic()
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--in", dest="infile", required=True,
                    help="the connection map's markdown, e.g. "
                         ".corpus/<channel_id>/connections-<brand_id>.md")
    ap.add_argument("--facts", default=None,
                    help="<channel_id>-facts.jsonl, the ledger, header first")
    ap.add_argument("--meta", default=None,
                    help="legacy <channel_id>-meta.json; read only when the "
                         "ledger carries no meta header")
    ap.add_argument("--out", default=None,
                    help="default: <facts dir>/<channel_id>-<brand_id>-connections.html, "
                         "or the input path with .html when --facts is omitted")
    ap.add_argument("--check", action="store_true",
                    help="validate the map against the page contract and exit "
                         "3 if it fails; writes nothing")
    ap.add_argument("--no-fragment", action="store_true",
                    help="skip the .fragment.html twin (written by default beside "
                         "the page, for hosts that publish body-only artifacts)")
    ap.add_argument("--brief", action="store_true",
                    help="render the creator-friendly brief instead of the "
                         "connections page; --in is creator-brief-<brand>.md")
    ap.add_argument("--connections", default=None,
                    help="--brief: the connections map the brief was written "
                         "from; a quote the map did not argue and the ledger "
                         "does not hold fails the check")
    ap.add_argument("--input", dest="brief_input", default=None,
                    help="--brief: creator-brief-input-<brand>.json, the brand's "
                         "own lines; each must appear verbatim")
    a = ap.parse_args()

    facts_path = pathlib.Path(a.facts) if a.facts else None
    facts, meta = load_ledger(facts_path, pathlib.Path(a.meta) if a.meta else None)
    in_path = pathlib.Path(a.infile)
    text = in_path.read_text(encoding="utf-8")

    if a.brief:
        if not a.connections:
            ap.error("--brief needs --connections <connections-<brand>.md>")
        map_md = pathlib.Path(a.connections).read_text(encoding="utf-8")
        inp = (json.loads(pathlib.Path(a.brief_input).read_text(encoding="utf-8"))
               if a.brief_input else None)
        problems = check_brief(text, facts, map_md, inp,
                               load_corpus_cues(pathlib.Path(a.connections)),
                               other_creator_names(pathlib.Path(a.connections),
                                                   parse_frontmatter(text)[0].get("channel_name")),
                               past_read_spots(pathlib.Path(a.connections)))
        if facts is None:
            problems.append("no ledger given: the quotes cannot be verified")
        if a.check:
            print(json.dumps({"in": str(in_path), "problems": problems,
                              "ok": not problems}, indent=1))
            funnel(stage="brief_check", problems=len(problems),
                   elapsed_s=round(time.monotonic() - t0, 1))
            raise SystemExit(3 if problems else 0)
        out_path = (pathlib.Path(a.out) if a.out
                    else default_brief_out(in_path, facts_path, parse_frontmatter(text)[0]))
        title, page, fragment = render_brief(text, inp)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(page, encoding="utf-8")
        result = {"html": str(out_path.resolve()), "title": title, "problems": problems}
        if not a.no_fragment:
            frag_path = out_path.with_name(out_path.stem + ".fragment.html")
            frag_path.write_text(fragment, encoding="utf-8")
            result["fragment"] = str(frag_path.resolve())
        print(json.dumps(result))
        funnel(stage="brief_render", problems=len(problems),
               supplied=bool(inp and inp.get("supplied")),
               bytes=len(page.encode("utf-8")),
               elapsed_s=round(time.monotonic() - t0, 1))
        if problems:
            print("BRIEF CONTRACT: " + "; ".join(problems), file=sys.stderr)
        return

    brand_id = parse_frontmatter(text)[0].get("brand_id")
    moments = load_moments(in_path, brand_id)
    facts = link_clean_moments(facts, moments)
    problems = check_page(text, facts, meta, load_probe(in_path), moments)
    if moments is None and section_kinds(text, meta)["conn"]:
        # the concept links were never checked: the gate cannot pass by absence
        problems.insert(0, f"moments-{brand_id or '<brand_id>'}.json is missing or unreadable "
                           "beside the map; run moment_check.py before the map is checked")
    if a.check:
        print(json.dumps({"in": str(in_path), "problems": problems,
                          "ok": not problems}, indent=1))
        funnel(stage="check", problems=len(problems),
               elapsed_s=round(time.monotonic() - t0, 1))
        raise SystemExit(3 if problems else 0)

    out_path = (pathlib.Path(a.out) if a.out
                else default_out(in_path, facts_path, parse_frontmatter(text)[0]))
    meta = {**meta, "_seen": cast_appearances(in_path.parent)}
    title, (page, fragment) = render_connections(text, facts, meta)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(page, encoding="utf-8")
    result = {"html": str(out_path.resolve()), "title": title, "problems": problems}
    if not a.no_fragment:
        frag_path = out_path.with_name(out_path.stem + ".fragment.html")
        frag_path.write_text(fragment, encoding="utf-8")
        result["fragment"] = str(frag_path.resolve())
    # absolute paths only: a relative path is what the user could not open
    print(json.dumps(result))
    connections = len(section_kinds(text, meta)["conn"])
    funnel(stage="render", facts=len(facts or []), connections=connections,
           no_fit=not connections, problems=len(problems),
           bytes=len(page.encode("utf-8")),
           elapsed_s=round(time.monotonic() - t0, 1))
    if problems:
        print("PAGE CONTRACT: " + "; ".join(problems), file=sys.stderr)
    # The connections page is the deliverable; a no-fit page is still a result.
    tl_data.report_run(SKILL)


if __name__ == "__main__":
    main()
