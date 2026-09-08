# ThoughtLeaders - YouTube Data for Codex

The optional Git-backed plugin connects to `https://app.thoughtleaders.io/mcp`
and adds the `tl-mcp` research skill. It supports YouTube transcript evidence,
brand mentions, creator discovery and historical performance research, with
sponsorship intelligence as a principal use case. It requires a ThoughtLeaders
account and consumes that account's query credits. Authenticate through the
client connection flow; no tokens belong in this repository.

The plugin requires no CLI installation or shell execution for research. The
existing CLI, Claude plugin and `tl setup`/`tl update` continue independently.
When a user explicitly requests the CLI, `tl-mcp` defers to the CLI skill. When
both skills are available, the distinct name permits explicit `$tl-mcp` selection;
automatic selection remains a host/model decision. MCP offers no report creation,
purchase, payment or campaign-editing workflow.

## Git installation and updates

After this PR is merged, add the repository marketplace and install its plugin:

```sh
codex plugin marketplace add ThoughtLeaders-io/thoughtleaders-cli --ref main
codex plugin add thoughtleaders-youtube-data@thoughtleaders-mcp
```

For pre-merge review, use `--ref feature/mcp-skill-distribution` instead of `main`.
A full checkout is intentional: the marketplace references `plugins/` and the
maintained generator reads canonical references. For reproducible review, pin a
commit with `--ref <commit>` instead of following a moving branch.

Refresh a tracked Git source with:

```sh
codex plugin marketplace upgrade thoughtleaders-mcp
```

Then use the client's plugin update/reinstall flow and start a new task to pick
up skills. A pinned commit stays pinned; choose a new ref when changing versions.
These commands configure the user's client only when they run them; building or
installing the Python package does not configure the MCP plugin.

## Maintained sources and upload artifact

- `plugins/thoughtleaders-youtube-data/` owns MCP-specific guidance and metadata.
- `skills/tl/references/elasticsearch-schema.md` remains the canonical home of
  shared ES examples. The generator extracts only three selected JSON bodies,
  removing their exact CLI wrapper. It does not copy private prose, full schema
  catalogues, the business glossary, scripts or role-specific workflows.
- `query-examples.md` is generated. Edit the canonical source and regenerate;
  never independently edit the generated copy. Missing/duplicate headings or an
  unfamiliar wrapper fail generation. Live `tl_schema_*` results take precedence
  over static examples for current fields, permissions and query rules.

From the repository root:

```sh
python scripts/build_mcp_plugin.py --generate
python scripts/build_mcp_plugin.py
python scripts/build_mcp_plugin.py --output /tmp/thoughtleaders-youtube-data.zip
```

The ZIP contains only the explicitly allowlisted plugin files, with fixed order,
timestamps and modes, plus a sibling SHA-256 file. CI checks reference drift and
bundle boundaries. The same maintained plugin source supplies Git installations
and the upload; no second skill source is maintained. The Codex compatibility
manifest version tracks this plugin, independently of the unchanged CLI release.

For the existing **With MCP** public submission, retain the remote endpoint and
upload the generated bundle as skills/package material using the portal's current
upload controls. The public listing's skill content is a reviewed snapshot:
refreshing a Git marketplace does not update that public submission. This build
neither uploads nor submits anything. Portal acceptance, OAuth, and authenticated
research in a newly installed client require separate verification.

Official references: [package plugins](https://developers.openai.com/plugins/build/plugins)
and [submit plugins](https://developers.openai.com/plugins/deploy/submission).
