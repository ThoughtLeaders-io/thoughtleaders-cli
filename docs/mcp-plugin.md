# ThoughtLeaders shared MCP skills

The optional plugin connects to `https://app.thoughtleaders.io/mcp` and exports
three skills from maintained CLI sources:

| MCP skill | Purpose | Runtime |
|---|---|---|
| `tl-mcp` | General YouTube research and discovery | Connected MCP tools |
| `tl-keyword-research-mcp` | Validated filters, trend videos and channel targets | MCP, Python, writable files, host classifiers where required |
| `tl-channel-authenticity-mcp` | Complete engagement, curve, integrity and comment audit | MCP, Python, writable files, yt-dlp/YouTube access, two independent classifier calls |

Authenticate through the host connection flow. The account's access and query
credits still apply; no tokens belong in scripts, receipts or the repository.
Advanced skills require executable scripts, but no TL CLI installation or CLI
authentication. An unsupported runtime cannot complete those workflows merely by
loading their text. Actual target-host validation remains a release gate.

The existing CLI, Claude plugin and `tl setup`/`tl update` remain separate.
Explicit CLI requests select existing CLI skills. Distinct MCP names allow
explicit selection and avoid overwriting installed CLI skills. Automatic
activation with both installed is still a host/model behavior to validate.

## Maintained sources

The repository holds one copy of every script and reference. The plugin commits
only its hand-written files: `.codex-plugin/plugin.json`, `.mcp.json`, the three
entrypoint `SKILL.md` files and `tl-mcp/references/tool-selection.md`. Everything
else in the bundle is assembled at build time (and gitignored in the plugin
directory). `scripts/build_mcp_plugin.py` declares a reviewed dependency manifest,
rather than copying every file under `skills/`:

- `skills/tl-keyword-research/` and `skills/tl-channel-authenticity/` own the full
  methodology, processing scripts and references. Their bodies are generated
  verbatim into each MCP skill's `references/methodology.md`; command examples
  identify scripts/arguments, while the explicit MCP runtime guide governs how
  they execute. No regex command translation or second scoring implementation.
- `skills/_shared/tl_data.py` is the same data seam every CLI skill already
  uses (`db_pg`/`db_fb`/`db_es`/`cli_rows`/`whoami`, plus `query()` for full
  envelopes). In an MCP session it answers those calls from MCP tool receipts
  instead of the `tl` CLI; nothing else in the skills changes.
  `skills/_shared/mcp_run.py` owns the request/receipt runner. The bundle ships
  both once, at `skills/_shared/`, the same relative path the canonical scripts
  already import from.
- `skills/_shared/references/mcp-runtime.md` owns the execution adaptation.
  `plugins/thoughtleaders-youtube-data/` owns concise MCP entrypoints and metadata.
- `agents/*.md` own classifier/research prompts. The explicitly listed prompts
  are bundled with only their host-specific frontmatter removed.
- `skills/tl/SKILL.md` supplies an explicit public subset of terminology and the
  sponsorship matching method. The full internal glossary is not exported.
  `skills/tl/references/elasticsearch-schema.md` supplies three selected JSON
  examples. Live schema/tool definitions take precedence over static examples.

Assembled files are release artifacts, not source: change the canonical files.
Tests reject missing references, unpackaged links and unsafe bundled symlinks.
Unlisted files are excluded from the ZIP. Adding dependencies requires updating
the manifest.

## How the shared data boundary works

CLI scripts use the existing CLI provider by default. In an explicit MCP session,
shared operations prepare typed requests. The host calls the connected MCP tools,
captures complete JSON responses, and imports them as receipts. The same scripts
then resume, using prior receipts without issuing the same query again. Preserve
results, totals, aggregations, highlights, pagination, coverage and error metadata;
never reconstruct a large response manually from a displayed excerpt.

The concrete invocation is:

```sh
python3 SKILL_DIR/../_shared/mcp_run.py run --session SESSION_DIR \
  SKILL_DIR/scripts/probe.py --level topic "sustainable fashion"
python3 SKILL_DIR/../_shared/mcp_run.py ingest --session SESSION_DIR \
  --request REQUEST_ID --response RESPONSE_JSON
```

Use absolute paths. Repeat the original run until it completes, then read
`output_path`. For stdin use `--input FILE` before the script path. Split canonical
shell pipelines into completed output files and subsequent inputs. Sessions bind
evidence to their source and invocation context; use one new directory per
workflow/account and restart on expiry or source changes. Nothing passes OAuth
credentials to Python.

Keyword research retains validation, refinement, intensity and context checks.
Its report builder returns an inline report URL and config without saving a
record. Named report persistence is not provided by this MCP package.

Authenticity retains every required evidence group, YouTube comment collection
and two independent classifier passes. Failed collection is not an empty comment
section; incomplete/invalid classifier output cannot support a completed audit.
The classifier prompt is shared, while host execution replaces legacy agent names.
A backend collector may be needed if the target host cannot reach YouTube; that
is a deployment decision after runtime validation, not solved by packaging.

## Build and verify

From the repository root:

```sh
python3 scripts/build_mcp_plugin.py --generate    # assemble the plugin in place
python3 -m pytest tests/test_mcp_plugin.py
python3 scripts/build_mcp_plugin.py --output /tmp/thoughtleaders-youtube-data.zip
```

The ZIP contains the allowlisted files in fixed order, with fixed timestamps and
modes. A sibling SHA-256 file identifies the artifact. Plugin version `0.2.0`
tracks this package separately from the CLI release. Build and validation do not
publish, upload, install or authenticate anything.

## Local installation and static submission

Assembled files are not committed, so install from an assembled checkout, not
from a Git ref (a Git install would carry the advanced entrypoints without their
scripts):

```sh
python3 scripts/build_mcp_plugin.py --generate
codex plugin marketplace add /absolute/path/to/thoughtleaders-cli
codex plugin add thoughtleaders-youtube-data@thoughtleaders-mcp
```

After changing a canonical skill, run `--generate` again, then use the host
update/reinstall flow and start a new task.
Python package installation does not configure this MCP plugin.

For the public With MCP submission, retain the remote endpoint and upload the
built package using the portal controls. Skill content is a reviewed static
snapshot: updating Git does not update the submission. Ship only after the
actual target host passes authenticated workflow checks, including complete JSON
receipt transfer, representative keyword refinement, comment retrieval and both
classifier passes. Fixture parity and packaging tests establish source and local
processing behavior, not live host compatibility or portal acceptance.

Official references: [build skills](https://developers.openai.com/plugins/build/skills),
[package plugins](https://developers.openai.com/plugins/build/plugins), and
[submit plugins](https://developers.openai.com/plugins/deploy/submission).
