# Creating the workflow

There is a **CLI create endpoint** so this skill's blueprint becomes a real
workflow directly — no hand-off required:

```
POST /api/cli/v1/workflows/build      (Bearer auth — the CLI's surface)
```

A workflow created this way is **identical to one built in the web app** (same
`Workflow` / stage-`Campaign` / `FilterSet` objects) and shows up in the web app's
workflow list + detail immediately, where the team moves / edits / duplicates it.

> **Prerequisites.** The endpoint ships with backend **thoughtleaders PR #4192**
> (`create_full_workflow`, of which this is the Bearer twin) and is invoked by a
> `tl workflow` command that POSTs to it. Until both are live, use the **manual
> in-app assembly** at the bottom of this file — the blueprint is the exact same
> input either way, so nothing changes for the user-facing design work.

## Create it directly (preferred)

1. **Build + save the entry (Sourced) report first.** It's a *query* report
   populated by this skill (`tl-keyword-research`, `tl channels`, `tl recommender`,
   or `tl reports create`) and saved (`tl-save-report` / `tl reports create`) so it
   exists with an **id**. This is the only stage that starts with data; it must be
   a saved query so the stage stays live.
2. **POST the blueprint** to `/api/cli/v1/workflows/build`:

   ```json
   {
     "name": "<workflow name>",
     "report_type": 3,
     "steps": [
       { "title": "Sourced",         "include_report_ids": [<entryReportId>], "exclude_report_ids": [] },
       { "title": "Qualify",         "include_report_ids": [], "exclude_report_ids": [] },
       { "title": "Get face on screen", "include_report_ids": [], "exclude_report_ids": [] },
       { "title": "Reach out",       "include_report_ids": [], "exclude_report_ids": [] }
     ]
   }
   ```

   - `report_type`: **1** content · **2** brands · **3** channels · **8** sponsorships.
   - Steps are created **in order**; the first is the entry stage, the rest are
     empty **lists** channels move into. Keep any linked-report nesting shallow (≤1–2).
   - Only reports you may edit are linked (others are silently dropped); the
     workflow is owned by the caller.
   - One atomic call creates the workflow + stage campaigns + include/exclude
     report links + the exclude-earlier-stages chaining, and returns the workflow
     (with its `id`).
3. **Hand the user the "Open in app" link** from the response breadcrumb
   (`/#/workflows/<report_type>/<id>`) to start working the funnel: on a stage,
   filter the rows → bulk-select → **Move** to the next stage (Move / Remove are
   non-destructive; moved channels leave the source stage).

## The endpoints (reference)

| Action | Request | Auth |
|--------|---------|------|
| **Build a full workflow (name + stages + links)** | `POST /api/cli/v1/workflows/build` · `{ name, report_type, steps[] }` | **Bearer (CLI)** |
| Convert one report → 1-stage workflow | `POST /api/workflows` · `{ campaignId, workflowName }` | session |
| Add a stage | `POST /api/workflows/add-step` · `{ campaignTitle, workflowId }` | session |
| Delete a stage (owner only) | `DELETE /api/workflows/delete-step?stepId=` | session |
| Rename / delete the workflow | `PATCH` / `DELETE /api/workflows/:id` | session |
| Fetch a workflow + stages | `GET /api/workflows/:id` | session |
| Link a report / move entities on a stage | `PATCH` the stage filterset's `add_relation` action | session |

Only the **build** endpoint is on the CLI's Bearer surface; the rest are the web
app's session-authenticated management routes.

## Or assemble it in the web app (manual fallback)

If the build endpoint / `tl workflow` command isn't live yet, the user assembles
it from the blueprint by hand:

1. Open the saved entry report → **Convert to workflow** → name it. It becomes
   **stage 1**.
2. **Add stage** for each downstream stage, in blueprint order (each is an empty
   list; names persist across reloads).
3. **Link** supporting include/exclude reports where the blueprint calls for it
   (nesting ≤1–2 layers).
4. Set per-stage **columns** the team acts on (Face On Screen, Outreach email).
5. **Work the funnel:** filter a stage → select → **Move** to the next stage.

## What to hand the user

- The **entry report link** (populated, openable).
- Either the **"Open in app" workflow link** (direct-create path) or the
  **blueprint + assembly steps** (manual fallback).
- The one-line "how to work the funnel": *filter a stage → select → Move to next.*
