# Creating the workflow

**The design rule that picks the path: the entry stage must BE the query** —
the stage-1 campaign's own FilterSet holds the filter criteria. Today only the
in-app **Convert to workflow** flow achieves that (the saved query report
itself becomes stage 1). The CLI's `tl workflow create` builds a whole
workflow in one call, but its steps can only *link* reports into fresh empty
stages — so its entry stage is a list-wrapper around the query report, which
violates the rule. **Prefer the in-app Convert path; offer the CLI one-shot
only if the user explicitly accepts the wrapped-entry tradeoff.**

## Convert in the web app (preferred — stage 1 IS the query)

1. **Build + save the entry report first** so it exists as a saved **query**
   report (populated by `tl-keyword-research`, `tl channels`, `tl recommender`,
   or `tl reports create`). **Title it as the stage** ("Leads", "Sourced") —
   the report title becomes the stage title.
2. Open the saved entry report → **Convert to workflow** → name it. The report
   becomes **stage 1**, query filters and all — no wrapper, no nesting.
3. **Add stage** for each downstream stage, in blueprint order (each is an
   empty **list**; names persist across reloads).
4. **Link** supporting include/exclude reports where the blueprint calls for it
   (nesting ≤1–2 layers), and set per-stage **columns** the team acts on
   (Face On Screen, Outreach email).
5. **Work the funnel:** on a stage, filter → select → **Move** to the next
   stage (Move / Remove are non-destructive; moved channels leave the source
   stage).

## `tl workflow create` (one call — but the entry query gets wrapped)

POSTs `{name, report_type, steps}` to the Bearer endpoint
`/api/cli/v1/workflows/build` (`create_full_workflow`, the twin of the web
"New Workflow" builder; live in production since 2026-07). One atomic call
creates the workflow + stage campaigns + report links + the
exclude-earlier-stages chaining, and it appears in the web app immediately.

**The limitation:** every stage campaign is created with a **fresh empty
FilterSet**; steps accept only `{title, include_report_ids,
exclude_report_ids}`. The entry query can therefore only be *linked into*
stage 1 (`include_report_ids: [<entryReportId>]`) — stage 1 is a list-wrapper,
not the query itself. `tl reports update` can't fix it up afterwards either
(filterset edits are unsupported). Until the backend lets a step *adopt* an
existing report as the stage, use this path only with the user's explicit
okay.

```bash
tl workflow create --file blueprint.json        # add --yes to skip the confirm
```

`blueprint.json`:

```json
{
  "name": "Q3 Creator Outreach",
  "report_type": 3,
  "steps": [
    { "title": "Sourced",            "include_report_ids": [<entryReportId>], "exclude_report_ids": [] },
    { "title": "Qualify",            "include_report_ids": [], "exclude_report_ids": [] },
    { "title": "Get face on screen", "include_report_ids": [], "exclude_report_ids": [] },
    { "title": "Reach out",          "include_report_ids": [], "exclude_report_ids": [] }
  ]
}
```

- `report_type`: **1** content · **2** brands · **3** channels · **8** sponsorships.
- Stages are created **in order**; the rest are empty **lists** channels move
  into. Keep any linked-report nesting shallow (≤1–2).
- Only reports you may edit are linked (others are dropped); the workflow is
  owned by you.
- Use `--config '<json>'` for inline JSON, or `--name` / `--report-type` to
  supply/override those fields. `--json` / `--toon` for machine output.
- The command prints the new workflow **id** and an **"Open in app"** link
  (`/#/workflows/<report_type>/<id>`).

## The endpoints (reference)

| Action | Request | Auth |
|--------|---------|------|
| **Build a full workflow** (`tl workflow create`) | `POST /api/cli/v1/workflows/build` · `{ name, report_type, steps[] }` | **Bearer (CLI)** |
| Convert one report → 1-stage workflow | `POST /api/workflows` · `{ campaignId, workflowName }` | session |
| Add a stage | `POST /api/workflows/add-step` · `{ campaignTitle, workflowId }` | session |
| Delete a stage (any same-org collaborator) | `DELETE /api/workflows/delete-step?stepId=` | session |
| Rename / delete the workflow (delete is owner-only) | `PATCH` / `DELETE /api/workflows/:id` | session |
| Fetch a workflow + stages | `GET /api/workflows/:id` | session |
| Link a report / move entities on a stage | `PATCH` the stage filterset's `add_relation` action | session |

Only the **build** endpoint is on the CLI's Bearer surface; the rest are the web
app's session-authenticated management routes (used from the web UI).

## What to hand the user

- The **entry report link** (populated, openable).
- Either the **blueprint + in-app Convert steps** (preferred) or the **"Open in
  app" workflow link** (if the user chose the `tl workflow create` shortcut).
- The one-line "how to work the funnel": *filter a stage → select → Move to next.*

Never claim a workflow was created unless the user confirmed the in-app
conversion or a `tl workflow create` call actually returned one — otherwise you
prepared a blueprint.
