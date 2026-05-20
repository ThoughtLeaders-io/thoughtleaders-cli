---
name: tl-feedback
description: Compose and submit feedback about the current AI Agent session that used the `tl` CLI. Triggers on phrases like "send feedback", "report a problem with the session", "tell the team how this went", "submit session feedback", "feedback about tl", "this session was frustrating, send feedback", "tl feedback", "share this session with the team", "log issues from this run". Use it ONLY when the user wants to send a written report about the session to the ThoughtLeaders team — never on requests that just *use* `tl` to query data.
---

# Send a session-feedback report via `tl feedback`

The `tl feedback` command POSTs a markdown-formatted message to the ThoughtLeaders team's `#ai-feedback` Slack channel. The server-side endpoint prepends the user/org context (user, email, organisation, links into Django admin), so the body you send should contain **only the session-specific report** — do not try to restate the user's name or org yourself.

This skill produces that body. Do not invoke `tl feedback` until every section below is written.

## When to invoke

Trigger this skill **only** when the user is explicitly asking for feedback to be sent — phrases like "send feedback", "log a problem with this session", "share these issues with the team", "submit session feedback", "tl feedback". Do **not** trigger it when the user is asking `tl` to fetch data, build a report, or perform any other analytical task; in those cases the `tl-cli:tl` or `tl-cli:tl-report-builder` skills are the right ones.

If you are not sure whether the user wants the feedback sent now or is just venting, ask one clarifying question before composing the body. Otherwise proceed.

## What the body must contain

Write the body to a scratch buffer (do not stream it directly to the shell) and only send it once all four sections are present. Use the **Slack mrkdwn subset** of markdown — Slack does not render standard markdown:

| Want | Slack mrkdwn |
| --- | --- |
| Bold | `*bold*` (single asterisk) |
| Italic | `_italic_` |
| Strike | `~strike~` |
| Inline code | `` `code` `` |
| Code block | triple backticks |
| Block quote | `> text` |
| Bullets | leading `• ` (or `- `) |
| Link | `<https://example.com|label>` |

`**double-asterisk bold**`, `[text](url)` links, and `#` headers render as **plain characters** in Slack — do not use them.

### Required sections, in this exact order

1. **One-sentence summary of the session.**
   Lead with one sentence (no header, no bullets) describing what the user was trying to accomplish in this session and how it went overall (e.g. *"Pulled Q1 sponsored-channel rosters for three brands; ran into a sanitizer rejection on the third query and resolved it via `tl db pg`."*).

2. **User prompts and the work done.**
   Section header `*User prompts and actions taken*`. Then a bulleted list — one bullet per distinct prompt the user issued in the session, in order. Each prompt is the parent bullet (a short paraphrase of what they asked, in quotes). Under each prompt, indent sub-bullets listing every concrete tool call or shell command you ran to handle it. Examples:

   ```
   • _"Find me Holafly's sponsored channels in the last 6 months"_
       • `tl db pg "SELECT DISTINCT c.id, c.channel_name FROM …"`
       • `tl brands find Holafly`
   • _"Now show their evergreenness scores"_
       • `tl db es '{"aggs":{"channels":{"terms":{"field":"channel.id"}}}}'`
       • `tl db pg "SELECT id, channel_name, evergreenness FROM thoughtleaders_channel WHERE id IN (…)"`
   ```

   Include every prompt — even ones that were short clarifications. If you used a non-`tl` tool (`jq`, `duckdb`, Read, Edit, Bash), list it too. Do not dump full command output; one line per command is enough.

3. **Analysis section.**
   Section header `*Analysis: problems, frustrations, weaknesses*`. Write a few short paragraphs (no bullets needed) covering, in this order:
   - **Problems / data errors** encountered (e.g. sanitizer rejections, schema mismatches, missing fields, wrong field names, 5xx responses, slow endpoints). Quote the exact error text or command when relevant.
   - **User frustrations** signalled in their messages (impatience, asking the same question twice, "this isn't what I asked for", profanity, abandoning a thread). Be honest — the team needs the actual signal, not a sanitised version. Do not editorialise about whether the frustration was justified.
   - **Weaknesses / gaps in the `tl` CLI or skills** that surfaced. Concrete examples: missing filters, output formats that needed jq post-processing, schema docs that were wrong or out of date, commands that ought to exist but don't, places where you (the agent) had to guess.
   - **What went well** — keep this short (one or two sentences). Skip the section if nothing notably went well.

   If a category has nothing to report, write *"None observed."* under the heading rather than omitting the heading entirely. Do not invent problems to fill space.

4. **Anything else the user explicitly asked you to include.**
   If the user's "send feedback" request contained a specific message ("tell them the new find command is great"), append it verbatim under a final `*From the user*` section as a block quote.

## After the body is ready

Send it with `tl feedback` — pass the body as a single argument (heredoc / `$(cat <<EOF …)` works well for multi-line content):

```bash
tl feedback "$(cat <<'EOF'
<the body you composed>
EOF
)"
```

On success the CLI prints `Thanks! Your feedback was sent to the team.` Confirm to the user with a brief, neutral one-liner ("Sent."). Do not echo the full body back to the user — they wrote it with you, they don't need to re-read it.

If `tl feedback` exits non-zero (network failure, server error), show the user the raw error and offer to retry. Do not silently swallow failures — feedback that didn't reach Slack is the worst possible outcome here.

## What NOT to do

- Do not prepend user name, email, organisation, or admin links to the body. The server adds those.
- Do not use `**bold**` or `[text](url)` markdown — Slack will print the literal characters.
- Do not split the report into multiple `tl feedback` calls. One message, one call.
- Do not invent prompts or commands you did not actually use. If you can't recall, write *"(earlier commands not captured)"*.
- Do not mark the task complete until `tl feedback` exits 0.
