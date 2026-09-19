# Shared MCP skills validation

Validated in the local Codex environment on 10 September 2026. This records actual evidence, not a claim of public-listing acceptance or support in every host.

## Scope

Three MCP skills: general TL research, keyword research, channel authenticity. Creator brief is excluded. No backend source or deployed API was changed. Existing CLI interfaces/authentication remain in place. The plugin has independent version 0.2.0; no CLI package release was published during validation.

## Completed checks

- Full suite after final review adjustments: **601 passed**. Independent final review verified both fixes with 21 runtime tests and found no remaining blocker within its code-review scope.
- Official plugin validator and all three official skill validators passed.
- Deterministic bundle checks cover the explicit 46-file manifest, generated-source drift, packaged references, helper identity and standalone imports.
- CLI wheel built from its source distribution. Both standalone advanced CLI skill entrypoints import successfully from extracted wheel assets. MCP skill directories are not included in CLI skill discovery. The internal shared-support directory is included by the existing wheel rules, but has no SKILL.md and is not a discoverable skill.
- Full authenticity fixture runs real domain calculations through collection, MCP request suspension/receipts, two classifier files and final reporting. Scores/evidence equal the CLI fixture except cache provenance. External data and YouTube scraping are mocked in this fixture.
- Live keyword video search through connected MCP completed without a CLI call. A standing-desk query since 1 September returned two sample videos, enriched their channels, and retained total_matching_videos=123. This validates retrieval/processing, not a full multi-round topic-research evaluation.
- Live YouTube comment collection on Ei7EI54gpe4 with cap 10 returned two comments with text using Python 3.12 and installed yt-dlp. This proves local collection access, not access from another host.

## Live authenticity

The initial run collected caller/channel/video data but encountered transient MCP internal errors. Repeating the exact cohort query returned 25 peer IDs. The implemented explicit retry path retained failed receipts and resumed without replacing successful evidence. The final attempt stopped when a peer ES request (channel 107550, size 10) failed three times: two internal errors and then a connection failure. Across the attempts the live collector made 23 execution calls plus three schema reads; the parent also made one successful direct cohort-query retry. No final state, classifier batch or score was produced. A complete live run and classification result are still required before asserting live authenticity completion.

Evidence is held outside the source tree under `/private/tmp/tl-mcp-live-auth-20260910-v3/`, including failed-attempt history. Do not bypass the source/version or retry guards to reuse these as a completed new run. The final source includes reviewed retry-output invalidation and access-error classification fixes; start fresh for the next live validation.

## Runtime boundaries

Advanced skills require Python and writable files in the receiving host. Authenticity also needs working YouTube collection and two independent classifier calls. Host capability checks precede paid collection. Public plugin submission/import remains a reviewed static snapshot. Neither Git refresh nor a ZIP build updates that public listing.

This validation used David's superuser account. Ordinary-account entitlements and actual portal/ChatGPT-host execution need separate acceptance checks before a broad public availability claim.
