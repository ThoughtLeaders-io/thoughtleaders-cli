# tests_cli — live, read-only CLI integration tests

These tests exercise the **real `tl` command end-to-end against a live,
authenticated API**. They are the counterpart to `../tests/`, which unit-test
the command layer with the HTTP client mocked. Here nothing is mocked: each
test shells out to the installed `tl` binary and asserts on what the live API
actually returns. This is the only layer that proves the CLI and the API work
together over the wire.

## Hard rules for anything added to this directory

1. **READ-ONLY ONLY.** Every test must use commands that cannot create, update,
   or delete server-side state.
   - **Allowed:** `whoami`, `balance`, `describe`, `schema`, `db pg|es|fb` with
     **SELECT / search-only** queries (or `--pricing` dry-runs), and the read
     verbs of data commands (`*/show`, `*/history`, `*/find`, recommender
     reads, snapshot reads).
   - **Forbidden:** anything that writes — `reports create`, `credits buy` /
     `top-up`, `auth login` / `logout`, any POST/PATCH/DELETE-backed command,
     or a `db` query that is not a plain SELECT/search. When in doubt, leave it
     out.

2. **Use the real `tl` CLI command — do not mock.** Drive every test by
   shelling out to the `tl` binary via the `tl` / `tl_json` fixtures in
   `conftest.py` (they use `subprocess`). Do **not** import `tl_cli` internals
   and call functions directly, and do **not** patch `get_client` / `httpx` —
   that is what `../tests/` is for. The point of this directory is the wire.

3. **Keep queries cheap.** `db` queries cost credits. Use constant selects
   (`SELECT 1`), `size: 1` / `LIMIT 1`, leading-index filters, or `--pricing`
   dry-runs. Never run an unbounded scan or a full-table aggregate.

4. **Skip when there's no backend — unless a live run was demanded.** By
   default the suite auto-skips when `tl` is absent or the API is
   unreachable/unauthenticated (the `_live_api_or_skip` fixture probes
   `tl whoami`), so a developer with no API sees skips, not red. But when
   `TL_CLI_REQUIRE_LIVE=1` is set — as the `cli-integration` workflow does — an
   unreachable/unauthenticated backend becomes a hard **failure** instead. That
   is what makes a real outage, an expired/removed `TL_API_KEY`, or a broken
   deploy show up red in CI rather than hiding behind a green "all skipped".
   Keep both behaviours: skip locally, fail loud where a live check was asked
   for (route every "no backend" exit through `_no_backend`, never a bare
   `pytest.skip`).

## Running

```bash
pytest tests_cli/                      # uses the configured TL_API_URL + creds
TL_CLI_BIN=/path/to/tl pytest tests_cli/   # pin a specific tl build
```

Requires an authenticated CLI (`tl auth login`, or `TL_API_KEY`) and a
reachable `TL_API_URL`. These tests are **not** part of the default `pytest`
run (`testpaths = ["tests"]`) and are not run in CI — there is no live backend
there. Invoke them explicitly against a dev/staging/local API.
