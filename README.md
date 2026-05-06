# tl cli

ThoughtLeaders CLI — query sponsorship data, channels, brands, and intelligence from the terminal.

## Install

### As a developer

```bash
git clone https://github.com/ThoughtLeaders-io/thoughtleaders-cli.git
cd thoughtleaders-cli
python -m venv .venv
pip install -e .
```

### As a user

```bash
pipx install thoughtleaders-cli
# or
uv tool install thoughtleaders-cli
# or (but try to avoid it because just "pip" will not create a new venv for the product - only "uv" and "pipx" will do that)
pip install thoughtleaders-cli
```

Then set up:
```bash
tl auth login          # authenticate with ThoughtLeaders
tl setup claude        # install Claude Code plugin (optional)
tl setup opencode      # install OpenCode skill (optional)
```

## Quick Start

```bash
# Login
tl auth login

# Query sponsorships
tl sponsorships list status:sold brand:"Nike" purchase-date:2026-01

# Shortcut commands for sponsorship types
tl deals list brand:"Nike"                    # Agreed-upon sponsorships
tl deals list created-at:today                # Deals created today (date keywords: today, yesterday, tomorrow)
tl matches list                               # Possible brand-channel pairings
tl proposals list                             # Matches proposed to both sides

# Show a specific sponsorship
tl sponsorships show 12345

# Search videos (note: this only shows "your" videos)
tl uploads list q:code --csv

# Show upload details (supports colon-containing IDs)
tl uploads show 1174310:0BehkmVa7ak

# Search channels via raw SQL — `tl db pg` against thoughtleaders_channel
# (run `tl schema pg` once to confirm the live column set).
# NOTE: For topic / category discovery, prefer the recommender over
# `content_category` equality — `tl recommender top-channels "<tag>"`
# returns channels ranked by how strongly they load on the topic, not just
# rows where the single category code matches exactly.
tl db pg "SELECT id, channel_name, total_views FROM thoughtleaders_channel
          WHERE content_category = <COOKING_CODE> AND total_views >= 100000
          ORDER BY total_views DESC LIMIT 50 OFFSET 0"
tl db pg "SELECT id, channel_name FROM thoughtleaders_channel
          WHERE is_tl_channel = TRUE LIMIT 200 OFFSET 0"             # all TPP channels (~169)
# MSN status: filter on `media_selling_network_join_date IS [NOT] NULL`
# in the same raw SQL query (column is scrubbed from advertiser sandboxes).

# Show channel detail — accepts numeric ID or channel name.
# Names that match more than one active channel print a candidate list
# and exit; retry with a specific ID.
tl channels show 12345
tl channels show "Economics Explained"

# Find similar channels (recommender, 25 credits, Intelligence plan).
# msn: is tri-state (default msn:yes): yes = MSN only, no = non-MSN only, both = no filter.
# tpp: is tri-state (default tpp:both): yes = TPP only, no = non-TPP only, both = no filter.
# Same ID-or-name resolution rules as `channels show`.
tl channels similar 12345 --limit 10
tl channels similar "Tremending girls" min-score:0.85 --limit 5

# Recommender — discovery by category/demographic tag (Intelligence plan).
# `tags` is free; `top-*`, `inspect-*`, `similar-to-profile`, and `similar-brands-to-channel` cost 25 credits flat.
tl recommender tags                              # List every tag (free)
tl recommender tags cooking                      # Search tag names by substring
tl recommender top-channels "Cooking" msn:yes --limit 50  # Top channels for a tag
tl recommender top-profiles "Cooking" mbn:yes --limit 30  # Top brand profiles (one brand → potentially multiple profiles)
tl recommender top-brands "Cooking" --limit 30            # Top brands (deduped from profiles)
tl recommender inspect-channel 12345             # Per-tag breakdown of a channel's vector
tl recommender inspect-brand Nike                # Per-tag breakdown of a brand's ideal profile
tl recommender similar-to-profile 842            # Channels closest to a brand profile

# Brand intelligence
tl brands show Nike

# Run a saved report
tl reports run 42

# Comments — available on sponsorships, channels, brands, and uploads
tl sponsorships comment-list 12345
tl sponsorships comment-add 12345 "Looks good"
tl channels comment-add 7890 "Strong recent winners"

# Show information about the logged-in user
tl whoami

# Check credits
tl balance
```

## Credits

Every data query costs credits based on the type and number of results. Use `tl describe` to see credit rates and `tl balance` to check your balance.

```bash
tl describe                           # All resources + credit costs
tl describe show sponsorships --filters    # Available filters for sponsorships
tl balance                     # Your credit balance
```

# Terminology

ThoughtLeaders has its internal terminology that's exposed throughout this tool.

* **Brands** - Usually companies, sometimes individual products. Brands are the sponsors.
* **Channels** - Usually YouTube channels, sometimes podcasts. Channels are creators, they are being sponsored.
* **Sponsorships** - Either possible or realised business deals between brands and channels. There are several specific types of sponsorships:
    * *Deals* - Contractually agreed-upon sponsorships. AKA sold sponsorships. They can be either in a production pipeline or already published / live.
    * *Matches* - Possible matches between brands and channels, i.e. all pairings that ThoughtLeaders thinks could possibly be right for each other.
    * *Proposals* - Matches that are actually proposed to both sides to consider.
- **Adspots** — types of ads a channel carries (e.g. mention, dedicated video, product placement). Returned by `tl channels show`; each carries price/cost and computed CPM.

Sponsorships are the centre of attention in ThoughtLeaders - all other analytics and operations serve to produce or optimise sponsorships.
Note that the term "Sponsorship" is wide, and can encompass deals that yet need to be approved by either side. There is a funnel of
sponsorship types: the pool of Sponsorships is large, the pool of Matches (considered from either Brand or Channel side) is smaller,
the pool of Proposals is yet smaller, and the pool of Deals is the smallest.

# Integrations

## Requirements

- Python 3.12+
- [jq](https://stedolan.github.io/jq/)
- [ripgrep](https://github.com/BurntSushi/ripgrep)
- [duckdb](https://duckdb.org/)

## Claude Code Integration

If you use Claude Code, install the plugin for natural language access:

```bash
tl setup claude
```

This registers the ThoughtLeaders marketplace, installs the plugin, and copies skills to `~/.claude/` for short `/tl` invocation. If the `claude` binary isn't on PATH, it still installs the standalone skills and prints manual instructions for the plugin.

### Using the skills

Talk naturally in Claude Code:

```
/tl Which channels did we sponsor in Q1?
/tl sold sponsorships for Nike in Q1
/tl show me pending proposals with send dates in April
/tl what channels does Nike sponsor?
/tl check my balance
```

Resource-specific slash commands:
```
/tl-sponsorships pending with send dates in April
/tl-reports run my Q1 pipeline
/tl-balance
```

### Updating

```bash
tl setup claude                    # re-installs skills and updates plugin
```

## OpenCode Integration

```bash
tl setup opencode
```

This copies the tl skill to `~/.config/opencode/skills/` where OpenCode discovers it automatically. The agent will use it when you ask about sponsorships, deals, channels, or brands.

## Output Formats

By default, output is a styled table in the terminal and JSON when piped.

```bash
tl sponsorships list status:sold                          # Pretty table
tl sponsorships list status:sold --json                   # JSON
tl sponsorships list status:sold --json | jq '.results'   # Pipe to jq
tl sponsorships list status:sold --csv > sponsorships.csv # CSV
tl sponsorships list status:sold --toon                   # TOON (token-efficient for LLMs)
```

TOON (Token-Oriented Object Notation) is a compact text format designed to encode structured data with fewer tokens than JSON when feeding output back into an LLM. See [What the TOON format is](https://openapi.com/blog/what-the-toon-format-is-token-oriented-object-notation) for the specification.

## Documentation

- [Architecture & Design](docs/architecture.md) — full design doc covering commands, data scoping, credit metering, and server-side API
- `tl describe` — discover available resources, fields, filters, and credit costs from the CLI itself
- `tl <command> --help` — detailed help for any command

# Notes

* Tested with OpenCode and the `nemotron-cascade-2-30b-a3b-i1` local model.
