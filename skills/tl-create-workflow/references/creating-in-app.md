# Creating the workflow

**The `tl` CLI cannot create a workflow.** Every `/api/workflows*` route is
**session-authenticated** (the web app's), so it's off the CLI's Bearer surface —
there is no `/api/cli/v1/workflows/*` route and no `tl workflow` command today.
So this skill **designs + sources + emits a create-ready blueprint**, and the
user stands the workflow up in the **web app** from that blueprint. A workflow
built there is the same `Workflow` / stage-`Campaign` / `FilterSet` objects the
rest of the platform uses.

## Assemble it in the web app (the actual path)

1. **Build + save the entry (Sourced) report first**, so it exists with an **id**.
   It's a *query* report populated by this skill (`tl-keyword-research`,
   `tl channels`, `tl recommender`, or `tl reports create`) and saved
   (`tl-save-report` / `tl reports create`). This is the only stage that starts
   with data, and it must be a saved **query** so the stage stays live.
2. Open the saved entry report → **Convert to workflow** → name it. It becomes
   **stage 1**.
3. **Add stage** for each downstream stage, in blueprint order (each is an empty
   **list** channels move into; names persist across reloads).
4. **Link** supporting include/exclude reports where the blueprint calls for it
   (nesting ≤1–2 layers).
5. Set per-stage **columns** the team acts on (Face On Screen, Outreach email).
6. **Work the funnel:** on a stage, filter the rows → bulk-select → **Move** to
   the next stage. Move / Remove are non-destructive; moved channels leave the
   source stage.

## The blueprint (the create-ready plan you hand over)

Emit the plan as name + `report_type` + an ordered list of stages. It maps
one-to-one onto the in-app steps above (and would be the exact body of a future
create endpoint — see below):

```json
{
  "name": "<workflow name>",
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
- Stages are ordered; the first is the entry stage, the rest are empty **lists**
  channels move into. Keep any linked-report nesting shallow (≤1–2).

## The endpoints (reference)

All are the web app's **session-authenticated** management routes — none is on
the CLI's Bearer surface, so the CLI/agent cannot call them:

| Action | Request | Auth |
|--------|---------|------|
| Convert one report → 1-stage workflow | `POST /api/workflows` · `{ campaignId, workflowName }` | session |
| Build a full workflow (name + stages + links) — the web "New Workflow" builder | `POST /api/workflows/build` · `{ name, report_type, steps[] }` | session (ships with thoughtleaders **PR #4192**, `create_full_workflow`) |
| Add a stage | `POST /api/workflows/add-step` · `{ campaignTitle, workflowId }` | session |
| Delete a stage | `DELETE /api/workflows/delete-step?stepId=` | session |
| Rename / delete the workflow (delete is owner-only) | `PATCH` / `DELETE /api/workflows/:id` | session |
| Fetch a workflow + stages | `GET /api/workflows/:id` | session |
| Link a report / move entities on a stage | `PATCH` the stage filterset's `add_relation` action | session |

## Future: a direct CLI create (does not exist yet)

A Bearer twin of the web builder — `POST /api/cli/v1/workflows/build`, invoked by
a `tl workflow` command — would let this skill create the workflow in one atomic
call (workflow + stage campaigns + include/exclude report links + the
exclude-earlier-stages chaining, returning the workflow `id`), linking only
reports the caller may edit and owning the result. The blueprint above is already
its exact input, so nothing is wasted when it lands. **It is not implemented
today — do not POST to it, and never claim a workflow was created unless a call
actually returned one.**

## What to hand the user

- The **entry report link** (populated, openable).
- The **blueprint + in-app assembly steps** (Convert → Add stage → link → set
  columns).
- The one-line "how to work the funnel": *filter a stage → select → Move to next.*
