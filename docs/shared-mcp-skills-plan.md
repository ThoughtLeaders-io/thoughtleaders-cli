# Shared MCP skills implementation plan

Scope approved in the follow-up to the PR 100 review: ship TL research, keyword research and full channel authenticity from shared maintained sources. Creator brief is excluded from this release.

## Verified problem and reuse

PR 100 exports five files and no executable complex workflows. Four keyword scripts duplicate ES subprocess calls; authenticity has its own data wrapper. Backend CLI and MCP already share query executors. Start from current main plus PR 100 in an isolated worktree. Keep the existing CLI command surface, authentication and processing logic.

## Implementation

1. CLI repository: introduce a shared full-envelope data interface compatible with the row-oriented seam in creator brief PR 91. Default provider calls existing CLI commands; explicit MCP sessions exchange typed, hashed requests and receipts with the connected host. No credentials enter artifacts. Errors/withheld fields remain errors. Session evidence is scoped, source-versioned and never global.
2. Keyword research: replace duplicated fetch wrappers while keeping query builders and processing shared; retain totals, aggregations and samples. Add meaningful adapter and fixture parity tests. Keep explicit report persistence distinct from inline report generation.
3. Authenticity: route existing collection through the shared interface, retain scoring and classifier methodology, make scrape failures distinct from successful empty results and require complete classifier evidence before final scoring. Include the classifier prompt in the generated skill. All existing required audit groups remain required.
4. Packaging: extend deterministic export from canonical skill sources, scripts, references and prompts. Generate thin MCP execution instructions. Include every imported helper in each self-contained export, preserve CLI install paths, validate resources and source drift. Keep existing TL MCP research guidance connected to shared TL methodology.
5. Backend: no rewrite or endpoint expansion planned initially. Add a bounded hosted collector only if verified host/runtime limitations require it; document that concrete addition before implementation.

## Review adjustments

Independent plan review identified silent comment failure and incomplete classifier acceptance as invalid full-audit outcomes. Fix these within authenticity coverage handling. MCP suspension must not be swallowed by existing exception handlers. Validate request IDs, isolate receipts by session, pin invocation inputs and source fingerprint, preserve stdout until completion, and avoid recharging already completed queries on resume. Batch independent probes where feasible.

Final review also requires retries to invalidate derived partial outputs and explicit classification of real authentication/premium-field error codes. Unknown errors are not assumed transient. The bounded retry path preserves failed attempts and never replaces successful evidence or access refusals.

## Verification and rollout

Run existing skill tests plus request/receipt error and metadata tests, equivalent-evidence processing tests, installed bundle smoke tests without tl, skill/plugin validation and CLI packaging/setup regression checks. Exercise a real bounded MCP workflow and comment collection in the target runtime; inability to do so is a release limitation, not successful verification. Obtain independent final review before publishing.

Prepare reviewable changes and reproducible upload artifact first. Release readiness requires no unresolved full-workflow or CLI regressions. Public submission remains a reviewed static snapshot; record package version and hashes. Existing sources and dirty checkouts stay untouched. Overall size L, staged by shared runtime, each skill and packaging. No creator brief, payments, new auth system or general report-write API in scope.
