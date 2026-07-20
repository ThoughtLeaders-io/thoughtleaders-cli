# Pitfalls — the failure modes hand-built workflows hit

These come from real workflows the team built (and abandoned). Design around
them from the start; most of a good workflow is just not stepping on these.

## 1. A query where a list belongs (the big one)

Making stage 2+ a **query** instead of a **list** is the #1 breakage. A query
recomputes its members from the index every time — it has nothing to *hold* the
entities you move into it, so "moved" channels vanish on the next load. **Only
the entry stage is a query; everything after it is a list.** If the user wants
to "filter" a mid-funnel stage, that's a transient **view filter** on the
list's rows (narrow what's shown so you can bulk-select), not a query stage.

## 2. Empty pipeline

Delivering a funnel whose entry stage is empty (or filled with placeholder
channels) is a non-deliverable. The entry stage must be **sourced from real
index data** — `tl-keyword-research`, `tl channels`, `tl recommender`,
guide-brand look-alikes — with its breadth sense-checked against the goal.

## 3. Over-nesting linked reports

A stage can include/exclude other reports, which can themselves include others.
There's **no depth limit in the platform**, and deep/wide nests resolve
exponentially (slow) and become impossible to reason about ("this report
excludes that one, which includes this other one…"). **Cap it at 1–2 layers.**
Prefer a flat stage with its own filters over a clever nest. Historically people
added manual exclude-hacks to make a nested workflow usable — that's a smell,
not a pattern to copy.

## 4. Meaningless / churning stage names

Stages are reports; their names are the report titles and they **persist** on
the campaign (a real historical bug reverted them, now fixed). Pick names the
team already uses for its process ("Get face on screen", "Reach out",
"Contacted") — not generic CRM labels. Fewer meaningful stages beat many empty
ones nobody works.

## 5. Designing for one person on a shared object

A workflow is **shared** across the team by default. Don't design it around one
AM's private view; design the stages so several people can work them. (The
platform's own per-user view feature is what lets each person hide the reports
that aren't theirs — not something you configure here, but keep the shared
reality in mind when naming/structuring stages.)

## 6. Claiming you created it

The CLI can't create the Workflow object — you **design, source, and
blueprint**, and the user assembles it in the app (Convert → Add stage → …).
Never say "I created your workflow." Say "here's your populated blueprint and
the steps to stand it up."

## 7. Too many stages

A funnel with eight stages the team won't actually move channels through is
worse than four they will. Map stages to the team's *real* process steps and
stop where the process stops. Every stage is a report someone has to maintain.

## Quick checklist

- [ ] Entry stage is a **query**, populated from real data, breadth confirmed.
- [ ] Every later stage is a **list**.
- [ ] Nesting ≤ 1–2 layers; flat preferred.
- [ ] Stage names are the team's real process words.
- [ ] Per-stage columns the team acts on are noted.
- [ ] You blueprinted + handed off assembly — you didn't claim to have created it.
