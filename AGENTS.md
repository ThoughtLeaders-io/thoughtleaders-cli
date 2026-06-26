# Project Overview

**tl-cli** is a Python CLI for querying ThoughtLeaders sponsorship data (sponsorships, channels, brands, uploads, snapshots, reports, recommender). Built with Typer + Rich + httpx. Designed as an "AI agent-first tool" — the CLI handles data commands and output, while the user's AI agent (Claude) provides decision making.

# Architecture

## Entry Point & Command Registration

`src/tl_cli/main.py` creates the root Typer app and registers all subcommands via `app.add_typer()`. The console script `tl` maps to `tl_cli.main:cli`, which wraps the Typer app with top-level error handling (respects `--debug`). System commands (`auth`, `setup`, `balance`, `doctor`, `whoami`) are free and don't cost credits.

## Command Pattern (all data commands follow this)

Every data command in `src/tl_cli/commands/` uses explicit Typer subcommands:
- `show` — detail view by ID
- `history` — historical data list
- `create` / `add` — create new records (where applicable)

When adding a new data command, follow this pattern. See `sponsorships.py` for the reference implementation.

## Auth Flow (`auth/`)

- **PKCE + Auth0**: Browser-based login with localhost callback server (`login.py`)
- **Token Storage** (`token_store.py`): OS keyring primary, `~/.config/tl/credentials.json` fallback (chmod 0o600)
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
- **Gemini** - `tl setup gemini`
- **Codex** - `tl setup codex`
- **OpenCode** - `tl setup opencode`

This repo is also a Claude Code plugin, and can directly be installed as one.

### Bundled skills — when to invoke

- **`tl`** — the main skill for querying ThoughtLeaders data. Default for any sponsorship / channel / brand / upload / report question.
- **`tl-keyword-research`** — invoke whenever the user wants to find videos or channels by **content keywords** (topics, concepts, niches) that aren't covered by a curated recommender tag, OR to validate that a candidate channel's content actually touches a given topic. **Default output: a ranked, context-validated set of channels** (each flagged for sponsorability) — discovered via field-weighted ES relevance (`title` > `summary` > `transcript`), then sense-checked so channels that only use the keyword in an unrelated sense are dropped. The keyword-distribution shape (`{operator, keywords:[{keyword,count}]}`) is now an **opt-in mode**, produced only when the user explicitly asks for keyword counts / distribution. **Do not compose keyword sets by hand for `tl db es` content searches — delegate to this skill first.** See `skills/tl/SKILL.md` → *Channel & video discovery* for the four-path decision tree and when to use this vs the recommender / raw SQL.
- **`tl-save-report`**, **`adapt-tl-data`**, **`tl-views-guarantee`**, **`tl-top-partnerships`** — narrower workflows; the skill files document their own triggers. `tl-top-partnerships` is brand-user-facing: ranks a brand's sold sponsorships by live eCPM vs the sold-date projection and delivers a two-tab Google Sheet via `gws`.

### Skill content boundaries

Skills under `skills/` are split into a `SKILL.md` and one or more `references/*.md` files. To prevent drift, each fact has exactly one home:

- **CLI-shaped facts live in `SKILL.md`** — command surface, flags, filter syntax, output shapes, workflow, credit-cost curve, status-label mapping the CLI emits.
- **Schema-shaped facts live in `skills/tl/references/`** — table/column catalogues, accepted-query rules for raw DB engines (PG/ES/Firebolt), index constraints, field types, ID formats. This directory is the **single canonical home** for schema facts inside this plugin. It is a managed sync of the upstream `thoughtleaders-skills/tl-data/references/` (the source of truth across all TL agent surfaces); changes that originate here should be propagated upstream, and vice versa.
- **Business-shaped facts live in `skills/tl/references/business-glossary.md`** (or the equivalent glossary file) — revenue/pipeline definitions, performance grades, ownership semantics, MSN/TPP meaning, team rosters.

When adding or updating skill content, place the fact in its single home and link from the others. Do not duplicate or "quick-recap" content across files — recaps are the highest drift surface.

## API Response Envelope

All list endpoints return: `{ results, total, limit, offset, usage: { credits_charged, credit_rate, balance_remaining }, _breadcrumbs }`.

### Key Environment Variables

- `TL_API_URL` — API base (default: `https://app.thoughtleaders.io`)
- `TL_API_KEY` — Bearer token override for CI/scripts
- `TL_AUTH0_DOMAIN`, `TL_AUTH0_CLIENT_ID`, `TL_AUTH0_AUDIENCE` — Auth0 config

## Credit System

Every data query costs credits (rates vary by resource). `tl describe` shows rates, `tl balance` shows remaining. The `402` status means insufficient credits. Hooks automatically warn when balance drops below 500.

## Version Bumps

The version string is defined in three files and all three must be updated together:
- `pyproject.toml` — `version = "x.y.z"`
- `.claude-plugin/plugin.json` — `"version": "x.y.z"`
- `src/tl_cli/__init__.py` — `__version__ = "x.y.z"`

## Creating a release

A "release" means using the `gh` command to create a release on GitHub, named like the current package version number.

Warn the user if they are creating a release and the latest commit didn't bump the version number, and ask for confirmation before releasing.

## Coding

* Do not reference internal architecture of the ThoughtLeaders app in comments or skills. Specifially: do not reference internal table names, field names, API endpoints, Python modules or functions (including the sanitizer).
* Do not let server implementation details into skill files (anything under `skills/`). Skills describe *what the CLI does* from the user's seat — observable command surface, inputs, outputs, examples. Do not say "the server enforces X", "the API validates Y on its side", "the backend rejects Z" — those are mechanism notes that drift the moment the server changes. State the user-visible behaviour ("unknown keys come back as 400") without naming where it's enforced.
* **All `import` and `from X import Y` statements live at the top of the Python module file** — after the module docstring, before any code. No inline imports inside function bodies, no lazy imports for "speed" or "optional dependency" reasons. `from __future__ import …` goes at the very top (Python requires that). The only legitimate inline-import exception is **platform-conditional imports** that cannot succeed on the other platform (e.g. `import msvcrt` on Linux, `import termios`/`tty` on Windows) — those stay inside their `if sys.platform == …:` guard. If a circular-import problem makes a top-level import impossible, fix the circular dependency rather than working around it with an inline import.

# Updating

The `tl update --force` command will force an update of the `thoughtleaders-cli` package.
The auto-update feature keeps the package updated, by checking (cached) on each command invocation.

# Git commit rules

Do not reference internal architecture of the ThoughtLeaders app in commit messages.

When a feature is purely server-side but changes the data the CLI receives (e.g. adding, removing, or renaming a field on a response, changing a credit rate, expanding an enum), make a forced empty commit on the tl-cli repo (`git commit --allow-empty`) describing the change. This keeps the CLI repo's history a complete log of what users see, even when no client code had to change. The `tl changelog` command will read this log to show to the users.

# Be aware of tests

For every feature or change, explicitly consider whether tests need to be added or updated, on this repo or on the server repo — new endpoint, new model field, new CLI command, new validation rule, new error path, anything that changes user-visible behaviour. Don't ship a feature without asking "what test covers this?" If no test does and the surface is non-trivial, write one. This applies across all repos involved in the change (server-side changes that ripple into the CLI need both server tests and CLI tests updated).

Be sure to check if tests need to be updated when changing any data structures or function names, in all repos involved in the change