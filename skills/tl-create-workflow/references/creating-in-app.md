# Creating the workflow

**`tl workflow create` builds the workflow from a blueprint in one call** — it
POSTs `{name, report_type, steps}` to the Bearer endpoint
`/api/cli/v1/workflows/build` (the twin of the web "New Workflow" builder). The
result is the same `Workflow` / stage-`Campaign` / `FilterSet` objects the rest of
the platform uses, so it shows up in the web app's workflow list/detail
immediately, where the team moves / edits / duplicates it.

> **Availability.** The `tl workflow` command ships in this repo; the endpoint it
> calls ships with backend **thoughtleaders PR #4192** (`create_full_workflow`).
> Until that backend change is deployed, `tl workflow create` returns an error —
> use the **manual in-app assembly** at the bottom of this file. The blueprint is
> the exact same input either way, so nothing is wasted.

## Create it directly (preferred)

1. **Build + save the entry (Sourced) report first**, so it exists with an **id**.
   It's a *query* report populated by this skill (`tl-keyword-research`,
   `tl channels`, `tl recommender`, or `tl reports create`) and saved
   (`tl-save-report` / `tl reports create`). This is the only stage that starts
   with data, and it must be a saved **query** so the stage stays live.
2. **Write the blueprint to a file** and run `tl workflow create`:

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
   - Stages are created **in order**; the first is the entry stage (link the saved
     query report via `include_report_ids`), the rest are empty **lists** channels
     move into. Keep any linked-report nesting shallow (≤1–2).
   - Only reports you may edit are linked (others are dropped); the workflow is
     owned by you. One atomic call creates the workflow + stage campaigns +
     include/exclude report links + the exclude-earlier-stages chaining.
   - Use `--config '<json>'` for inline JSON, or `--name` / `--report-type` to
     supply/override those fields. `--json` / `--toon` for machine output.
3. The command prints the new workflow **id** and an **"Open in app"** link
   (`/#/workflows/<report_type>/<id>`). Hand that to the user to work the funnel:
   on a stage, filter → bulk-select → **Move** to the next stage (Move / Remove
   are non-destructive; moved channels leave the source stage).

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

## Assemble it in the web app (fallback until the endpoint is live)

If the build endpoint isn't deployed yet, the user stands the workflow up from
the blueprint by hand — same design, more clicks:

1. Open the saved entry report → **Convert to workflow** → name it. It becomes
   **stage 1**.
2. **Add stage** for each downstream stage, in blueprint order (each is an empty
   **list**; names persist across reloads).
3. **Link** supporting include/exclude reports where the blueprint calls for it
   (nesting ≤1–2 layers).
4. Set per-stage **columns** the team acts on (Face On Screen, Outreach email).
5. **Work the funnel:** on a stage, filter → select → **Move** to the next stage.

## What to hand the user

- The **entry report link** (populated, openable).
- Either the **"Open in app" workflow link** (from `tl workflow create`) or the
  **blueprint + in-app assembly steps** (fallback).
- The one-line "how to work the funnel": *filter a stage → select → Move to next.*

Never claim a workflow was created unless a `tl workflow create` call actually
returned one — otherwise you prepared a blueprint.
