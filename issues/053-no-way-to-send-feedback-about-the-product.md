---
title: "A reader has no way to send feedback about the product"
labels: [wayfinder:task]
parent: 000-map
blocked_by: []
assignee: null
status: open
---

## The gap

A reader gets a verdict, a credible interval and an analyst to interrogate, and then has no
way to say anything back — about any of it. Not *"this was confusing"*, not *"I wanted X"*,
not *"the verdict looked wrong to me."*

There is no channel at all. Every signal about whether this product is any good currently
has to be inferred.

## What it is for

Product feedback, in the reader's own words. Which covers more than one thing, and the
range is the point:

- *"I could not tell what to do with this."* — the gap [044](044-report-says-what-won-not-what-to-change.md) exists to close, reported by the person who felt it
- *"I did not understand the interval."* — which is [018](018-audience-research-knowledge-base.md)'s subject, and a reader saying so is evidence 018 is worth building
- *"I wanted to export this."* — a feature request that no amount of internal reasoning produces
- *"this verdict looks wrong."* — worth having, and the closest thing to a signal about
  015's failed negative control, though a free-text box collects **opinions, not outcomes**
  (see *Out of scope*)

**No claim that this validates anything.** The channel's value is that the product
currently has none, not that opinions substitute for measurement.

## Store it, do not email it

This is the ticket's main engineering decision.

| approach | why not |
|---|---|
| POST that sends mail (Resend, SMTP) | a new dependency, a new API key in the environment, a new paid service — and an **unauthenticated endpoint that mails a fixed address is an inbox-flooding vector**, which [045](045-paid-endpoints-have-no-auth-or-rate-limit.md) records nothing currently prevents |
| `mailto:` link in the app | depends on the reader having a mail client configured, which many browser users do not, and drops the feedback if they abandon the draft |
| **a `feedback` table** | **no new dependency** — `psycopg` is already direct, and `schema.sql` + `apply_schema` is the established pattern for a new table |

Notification is a separate concern and deliberately not here. A row nobody has read yet is
still strictly better than no row, and the fix for that is a query, not an email provider.

**The hiring contact link is not this ticket.** *"Would you like to hire me"* belongs in the
README and the page footer as a plain `mailto:` — no code, and it serves a visitor rather
than a reader mid-report. Bundling them makes both worse.

## Attach what they were looking at, cheaply

Feedback reading *"the report was confusing"* is more useful with the report beside it. The
payload is already in the browser — `EvaluateForm` holds it as `state.result` — so
including it costs a field, not a fetch.

Two cautions if it is included:

- **Nothing persists a finished test**, per `ChatRequest`: *"the votes ledger stores votes,
  not verdicts."* `schema.sql` has `personas` and `votes` and no verdict anywhere. So the
  payload travels *with* the feedback rather than being referenced — the same reason
  `ChatRequest` already sends the whole result.
- **Do not store `votes[0].test_id` as "this run".** `pipeline.py:258`: *"A cached vote
  keeps the test_id of the run that paid for it."* One response's votes can carry several
  different ids, so a single-`test_id` column would be quietly wrong.
  [047](047-nothing-correlates-a-log-line-to-its-run.md) wants a real run identifier for
  its own reasons; until it exists, the payload is the identifier.

Optional rather than required: feedback with no report attached is still worth keeping.

## Scope

- A `feedback` table via `schema.sql` + `apply_schema` — the text, the report payload when
  present, a timestamp.
- One endpoint that writes a row, off the paid path, adding nothing to `/evaluate`'s
  latency.
- **Bound the text**, following the precedent already in `ChatRequest`:
  `Field(min_length=1, max_length=MAX_CHAT_MESSAGE_CHARS)`. An unbounded column behind an
  open endpoint is a storage-filling vector.
- A form in the report, near where the reader already is. It is a sibling concern to
  `AnalystDock`, and [049](049-a-render-error-loses-the-paid-report.md) argues each sibling
  gets its own error boundary so neither can blank the verdict.
- A failed write must not lose what the reader typed.

## Two things it must not do

**Never treat feedback as trusted text.** 018's security note says the corpus is trusted
*because* every document is chosen and committed — and that this *"stops holding the moment
anyone can upload a source."* **Feedback is that moment:** it is the first user-supplied
prose this system stores. If it is ever retrieved into a prompt, which is plausible since
*"what are readers saying?"* is a natural question to want answered, it belongs to
[013](013-guardrails-mvp.md)'s threat model and not to 018's trusted-corpus reasoning.
Worth writing down now, while the answer is simply *"nothing reads it."*

**Do not keep it forever without deciding to.** An attached payload carries the reader's
**unreleased marketing copy** — confidential content, not just an opinion.
[040](040-vote-cache-read-window.md) already reasoned about retention for votes and
[046](046-analyst-threads-die-on-restart.md) left thread expiry open; this lands in the same
place and deserves the same answer rather than a silence.

## Out of scope, named so nobody assumes it

- **Outcome reporting.** *"We shipped B and here is what happened"* is the feedback that
  would genuinely test the panel against reality, and it is a different feature: it needs
  the reader to return weeks later, which needs a durable link, identity and a reason to
  come back. Depends on [045](045-paid-endpoints-have-no-auth-or-rate-limit.md).
- **Notification.** No email provider, no webhook, no digest.
- **Human-in-the-loop approval.** A separate ticket and a genuinely different feature —
  pausing execution for confirmation before `/evaluate` spends money. Nothing here pauses
  anything, and the term is worth reserving for the thing it means.

## Done when

A reader can send feedback from the report in their own words, it lands in Postgres with the
report they were looking at when present, a failed write does not lose what they typed, and
nothing reads the stored text back into a prompt.
