# Assembling the workflow (in the web app)

The `tl` CLI has **no workflow command**, and the workflow endpoints are
session-authenticated (the CLI authenticates with a Bearer token against
`/api/cli/v1/…`, a different surface). So the Workflow object itself is built in
the web platform. This skill prepares everything up to that point (design +
sourced entry report + blueprint); this file is the hand-off the user follows.

## The create flow, today

The platform creates a workflow by **converting an existing report** into a
one-stage workflow, then adding stages:

1. **Build the entry (Sourced) report first** — a *query* report populated by
   this skill (via `tl-keyword-research`, `tl channels`, `tl recommender`, or
   `tl reports create`). Save it (`tl-save-report` / `tl reports create`) so it
   exists as an openable report.
2. **Open that report in the platform → "Convert to workflow" → name it.** The
   report becomes **stage 1**. (There is no "new blank workflow from scratch"
   builder today — you start from a report and convert.)
3. **Add each downstream stage** with the platform's **Add stage** control, in
   order, using the names from the blueprint. Each new stage is an empty **list**
   report. Stage names save on the campaign and persist across reloads.
4. **Link supporting reports** on a stage where the blueprint calls for it
   (include / exclude another report) — keep nesting shallow (≤1–2 layers).
5. **Set per-stage columns** the team acts on (Face On Screen, Outreach email).
6. **Work the funnel:** on a stage, filter the rows, bulk-select, and **Move**
   the selection to the next stage. Move / Remove are non-destructive.

## The endpoints (reference only — not callable from the CLI's Bearer auth)

For context / future automation. All are session-auth under `/api/workflows`:

| Action | Request |
|--------|---------|
| Convert a report → workflow | `POST /api/workflows` · `{ campaignId, workflowName }` → new 1-stage workflow |
| Add a stage | `POST /api/workflows/add-step` |
| Delete a stage | `DELETE /api/workflows/delete-step` |
| Rename the workflow | `PATCH /api/workflows/:id` · `{ name }` |
| Delete the workflow (owner only) | `DELETE /api/workflows/:id` |
| Fetch a workflow + stages | `GET /api/workflows/:id` |
| Link a report to a stage / move entities | `POST` to the stage filterset's `add_relation` |

**Known limitation to flag to the user:** because create only *converts an
existing report*, there is no single "create a full multi-stage workflow (name +
stages + links) in one call". Building the funnel is convert-then-add-stage,
one stage at a time, in the UI. If a from-scratch multi-stage builder ships
later (or a CLI endpoint is added), this skill's blueprint is already the exact
input it would need — so nothing is wasted.

## What to hand the user

- The **entry report link** (populated, openable).
- The **blueprint** (stage names, types, per-stage columns, any linked reports).
- These **six assembly steps**, condensed to their situation.
- The one-line "how to work the funnel": *filter a stage → select → Move to
  next.*
