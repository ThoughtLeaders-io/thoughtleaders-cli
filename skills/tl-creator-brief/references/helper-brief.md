# The helper brief

This is the whole of what each helper agent receives in Step 3. Fill in the
placeholders from Step 2 and pass it verbatim. Nothing else goes with it: not the
brand, not the rest of the skill, not the other agents' returns.

**Never name the brand in here.** A helper that knows the brand narrows to the
brand without being asked, and the offhand detail that makes a real connection
never comes back.

---

You are given a list of candidate passages from one YouTube channel's
transcripts, each with a video id, a timestamp, and its attribution signals.

The channel is `<channel name>`. Its dominant format is `<format>`. The host is
`<host name>`, and these are the facts already known about them:
`<known facts from the identity step>`.

Each passage carries its video title, and where Step 2 detected a different
format for that video, that video's format too. **A passage's own video format
wins over the channel's**, because one channel mixes formats.

Apply the three-part self-reference test in `references/evidence-rules.md` to
every passage, and return only those that pass all three parts.

Then attribute, into three buckets rather than a yes or no. **Which rule
applies depends on the format of the video the passage came from**, so read that
first.

**Where one voice holds the transcript (solo talking head).** No attribution
signal is required. A passage that passes the three-part test is **Confirmed**.
The absence of `host_anchor` means nothing here, because a host rarely says his
own name. Use **Unconfirmed** only for the genuine exception, where a clip, a
quoted line or another voice makes the speaker unclear.

**Where another voice shares the transcript (interview, multi-host, reaction).**
Use the signals:

- **Confirmed.** `host_anchor`, `in_sponsor_read`, or a `recurrence_videos` of
  3 or more. These are strong signals that the host is speaking.
- **Unconfirmed.** `weak_anchor`, which is first-person talk about running a
  show or a business. Roughly half of these are the other voice talking about
  their own. **Keep them and label them unconfirmed. Do not drop them.** The
  label is what protects the reader, not the deletion.
- **Unattributable.** No signal at all, and nothing in the surrounding lines
  names the speaker. Drop these.

Wherever a second voice is present, most self-disclosure in the transcript
belongs to it rather than to the host, so never upgrade a passage to confirmed by
guessing. A quote presented as the host's when someone else said it is the one
error that discredits everything around it, and the bucket label is how that is
avoided. On an interview channel that second voice is the guest, and the guest
usually talks more than the host does.

In a **reaction** video the narration of the material being reacted to sits in
the same transcript with no speaker labels, so a passage from one is
**Unconfirmed** at best unless `host_anchor` or `in_sponsor_read` is true.

For each passage you keep, return the verbatim words, the video id, the
timestamp, one short phrase on what it reveals about the creator, and its
attribution bucket. Then state how many you dropped and the most common reason.

One trap to expect: **a possessive is only a life fact if the thing possessed
belongs to the speaker's life.** On a channel about games or sport, "my team",
"my squad" and "my run" are almost always objects in that video's subject
matter. Reject those on the three-part test rather than treating the possessive
as disclosure.

Return nothing else: no raw transcript, no commentary, no summary of the
channel's topic. Do not look for further material beyond the list you were
given.
