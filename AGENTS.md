# Project Overview

**tl-cli** is a Python CLI for querying ThoughtLeaders sponsorship data (sponsorships, channels, brands, uploads, snapshots, reports, recommender). Built with Typer + Rich + httpx. Designed as an "agent-first tool" — the CLI handles structured commands and output, while the user's AI agent (Claude) provides intelligence.

# Architecture

## Entry Point & Command Registration

`src/tl_cli/main.py` creates the root Typer app and registers all subcommands via `app.add_typer()`. The console script `tl` maps to `tl_cli.main:cli`, which wraps the Typer app with top-level error handling (respects `--debug`). System commands (`auth`, `setup`, `balance`, `doctor`, `whoami`) are free and don't cost credits.

## Command Pattern (all data commands follow this)

Every data command in `src/tl_cli/commands/` uses explicit Typer subcommands:
- `list` — list/search with `key:value` filters as positional args
- `show` — detail view by ID
- `history` — historical data list
- `create` / `add` — create new records (where applicable)

When adding a new data command, follow this pattern. See `sponsorships.py` for the reference implementation.

`deals`, `matches`, and `proposals` are shortcut commands that delegate to sponsorships' `do_list`/`do_show`/`do_create` with a pre-set status filter. They reject explicit `status:` filters — users should use `tl sponsorships list` for finer-grained status filtering.

`recommender` (`commands/recommender.py`) wraps the recommender API at `/api/cli/v1/recommender/*` — `tags` (free), `top-channels` / `top-profiles` / `top-brands`, `inspect-channel`, `inspect-brand`, `similar-to-profile` (all 25 credits flat, Intelligence-gated). The three `top-*` URLs share one server resolver; `top-brands` dedupes the underlying profile rows by brand. Channel→channel and brand→brand similarity stay on `tl channels similar` / `tl brands similar`. When updating the SKILL or examples, prefer steering category/topic discovery (e.g. "Cooking channels") to `tl recommender top-channels "<tag>"` rather than `WHERE content_category = <code>` SQL — the recommender is ranked, not equality-based. The underlying recommender code uses "element"/"field_name" terminology; the CLI/API layer renames these to "tag" at the boundary.

## Filter Parsing (`filters.py`)

`parse_filters()` handles `key:value` and `key:"quoted value"` syntax. Returns `dict[str, str]` passed as query params. Date filter keys (listed in `DATE_FILTER_KEYS` — e.g. `since`, `created-at`, `created-at-start`, `publish-date-end`) accept keywords `today`, `yesterday`, `tomorrow`. Sponsorship date fields (`created-at`, `publish-date`, `purchase-date`, `send-date`) each expose three filter shapes: bare `<field>:<date>` matches within that date/period, and `<field>-start:` / `<field>-end:` give inclusive lower/upper bounds (both sides inclusive; partial dates expand to the whole period). Empty-string values result in `IS NULL` queries on the backend.

## Auth Flow (`auth/`)

- **PKCE + Auth0**: Browser-based login with localhost callback server (`login.py`)
- **Token Storage** (`token_store.py`): OS keyring primary, `~/.config/tl/credentials.json` fallback (0o600)
- **Env override**: `TL_API_KEY` env var takes priority over keyring (for CI)
- **Auto-refresh**: `TLClient` refreshes expired tokens on 401

## HTTP Client (`client/http.py`)

`TLClient` wraps httpx with auth header injection and automatic token refresh on 401. All API calls go through `_request()`.

Every request includes an `X-TL-Client: cli/<version>` header. This header is used server-side in a Cloudflare WAF rule to skip managed challenges (JS/CAPTCHA) for CLI traffic on `/api/cli/*` paths. The header is not a secret — Cloudflare bypass is safe because the API enforces its own auth via Bearer tokens. If Cloudflare starts blocking CLI requests again, verify the WAF rule matches the current header value.

## Error Handling (`client/errors.py`)

Exit codes: 1 (forbidden/not-found), 2 (auth required), 3 (rate-limit/server-error), 4 (insufficient credits).

## Output (`output/formatter.py`)

TTY-aware: Rich tables in terminal, JSON when piped. Flags: `--json`, `--csv`, `--md`. Usage footer (credits charged + balance) goes to stderr. Breadcrumbs suggest next commands.

## AI Agent Integration

The CLI integrates with AI coding agents via skills, commands, agents, and hooks.

- **Claude Code** - `tl setup claude`
- **OpenCode** - `tl setup opencode`

This repo is also a Claude Code plugin, and can directly be installed as one.

### Bundled skills — when to invoke

- **`tl`** — the main skill for querying ThoughtLeaders data. Default for any sponsorship / channel / brand / upload / report question.
- **`tl-keyword-research`** — invoke whenever the user wants to find videos or channels by **content keywords** (topics, concepts, niches) that aren't covered by a curated recommender tag, OR to validate that a candidate channel's content actually touches a given topic. Returns `{operator, keywords:[{keyword,count}]}` from a ranked ES probe over `title` / `summary` / `transcript`; the caller then runs the actual content search with the surviving high-count terms. **Do not compose keyword sets by hand for `tl db es` content searches — delegate to this skill first.** See `skills/tl/SKILL.md` → *Channel & video discovery* for the four-path decision tree and when to use this vs the recommender / raw SQL.
- **`tl-report-builder`** — invoke when the user wants to build, refine, or save a platform report (campaign config, FilterSet, columns, widgets). Multi-phase flow: routing → schema + validation → columns → widgets.
- **`tl-import`**, **`tl-save-report`**, **`adapt-tl-data`** — narrower workflows; the skill files document their own triggers.

### Skill content boundaries

Skills under `skills/` are split into a `SKILL.md` and one or more `references/*.md` files. To prevent drift, each fact has exactly one home:

- **CLI-shaped facts live in `SKILL.md`** — command surface, flags, filter syntax, output shapes, workflow, credit-cost curve, status-label mapping the CLI emits.
- **Schema-shaped facts live in `skills/tl/references/`** — table/column catalogues, accepted-query rules for raw DB engines (PG/ES/Firebolt), index constraints, field types, ID formats. This directory is the **single canonical home** for schema facts inside this plugin. It is a managed sync of the upstream `thoughtleaders-skills/tl-data/references/` (the source of truth across all TL agent surfaces); changes that originate here should be propagated upstream, and vice versa.
- **Business-shaped facts live in `skills/tl/references/business-glossary.md`** (or the equivalent glossary file) — revenue/pipeline definitions, performance grades, ownership semantics, MSN/TPP meaning, team rosters.

When adding or updating skill content, place the fact in its single home and link from the others. Do not duplicate or "quick-recap" content across files — recaps are the highest drift surface.

#### Anti-pattern: skill-local schema references

When a dependent skill (e.g. `tl-report-builder`) needs to reference a schema fact (table layout, columns, fetch SQL, hallucinated-column markers), **link to the canonical home in `skills/tl/references/`** — do not create a new `<skill>/references/*.md` file that mirrors or paraphrases that content.

Concrete regression marker: an earlier branch added `skills/tl-report-builder/references/data_plane.md` to consolidate the `thoughtleaders_topics` fetch query out of inline tool text. That had the right *shape* (don't restate schema in tool prose) but the wrong *home* — it forked schema facts into a parallel reference file that would silently drift from `skills/tl/references/postgres-schema.md`. The fix was to land the columns + fetch SQL + regression markers in `postgres-schema.md` (and upstream in `tl-data/references/postgres-schema.md`), delete the local file, and rewire the references via Markdown links.

Rule of thumb: if you are about to write *"here's the SQL to query this table"* or *"these columns don't exist on this table"* anywhere outside `skills/tl/references/`, stop. Add the fact to the canonical reference, then link to the anchor. Same for business facts and the glossary.

Skill-local `references/*.md` ARE appropriate when the content is **skill-shaped**, not schema-shaped:
- Column metadata for a specific report type (sortable columns, formula templates) — `tl-report-builder/references/columns_*.md`
- JSON schemas for tool-specific request/response shapes — `tl-report-builder/references/*_schema.json`
- Disambiguation tables, defaults, and pitfall catalogues that exist only in this skill's flow — `tl-report-builder/references/report_glossary.md`

If you are unsure whether a fact is schema-shaped or skill-shaped, ask: "would another TL skill (analyst, finance, mbn-outreach) ever need this fact?" If yes, it's schema/business-shaped — promote it to the canonical home.

## API Response Envelope

All list endpoints return: `{ results, total, limit, offset, usage: { credits_charged, credit_rate, balance_remaining }, _breadcrumbs }`.

### Key Environment Variables

- `TL_API_URL` — API base (default: `https://app.thoughtleaders.io`)
- `TL_API_KEY` — Bearer token override for CI/scripts
- `TL_AUTH0_DOMAIN`, `TL_AUTH0_CLIENT_ID`, `TL_AUTH0_AUDIENCE` — Auth0 config
- `TL_LLM_KEY` — User's own LLM key for `tl ask` (avoids surcharge)

## Credit System

Every data query costs credits (rates vary by resource). `tl describe` shows rates, `tl balance` shows remaining. The `402` status means insufficient credits. Hooks automatically warn when balance drops below 500.

## Version Bumps

The version string is defined in three files and all three must be updated together:
- `pyproject.toml` — `version = "x.y.z"`
- `.claude-plugin/plugin.json` — `"version": "x.y.z"`
- `src/tl_cli/__init__.py` — `__version__ = "x.y.z"`

## Important Constraint

`tl snapshots video` requires `--channel` flag — Firebolt queries without a channel partition are unbounded.

## Coding

* Do not reference internal architecture of the ThoughtLeaders app in comments or skills. Specifially: do not reference internal table names, field names, API endpoints, Python modules or functions (including the sanitizer).
* Do not let server implementation details into skill files (anything under `skills/`). Skills describe *what the CLI does* from the user's seat — observable command surface, inputs, outputs, examples. Do not say "the server enforces X", "the API validates Y on its side", "the backend rejects Z" — those are mechanism notes that drift the moment the server changes. State the user-visible behaviour ("unknown keys come back as 400") without naming where it's enforced.
* Place all imports at the start of the Python module file

# Git commit rules

Do not reference internal architecture of the ThoughtLeaders app in commit messages.

When a feature is purely server-side but changes the data the CLI receives (e.g. adding, removing, or renaming a field on a response, changing a credit rate, expanding an enum), make a forced empty commit on the tl-cli repo (`git commit --allow-empty`) describing the change. This keeps the CLI repo's history a complete log of what users see, even when no client code had to change.

# Be aware of tests

For every feature or change, explicitly consider whether tests need to be added or updated — new endpoint, new model field, new CLI command, new validation rule, new error path, anything that changes user-visible behaviour. Don't ship a feature without asking "what test covers this?" If no test does and the surface is non-trivial, write one. This applies across all repos involved in the change (server-side changes that ripple into the CLI need both server tests and CLI tests updated).

Be sure to check if tests need to be updated when changing any data structures or function names, in all repos involved in the change.