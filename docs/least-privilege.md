# What defends this product, and what would stop defending it

The security requirement asks for guardrails. Most of the defence here is not a
guardrail at all — it is the shape of the system. This is that argument written
down, so a change that quietly removes one of these reads as removing a defence
rather than simplifying a design.

It is deliberately organised around **what would make it false**. An assessment
that only says why things are safe today ages into a false sense of security the
moment the system moves, and nothing fails to announce it.

## The only untrusted input is the customer's own text

Two headlines and a target description. That is the whole attack surface a
stranger controls.

Everything else that looks like it might be untrusted turns out not to be:

- **Personas are sampled or templated, never written by a model.** Every field
  comes from the OECD joint tables or the Big Five norms, and the prose a
  panelist reads is rendered from those numbers by `app/panel.py`. There is no
  LLM-authored content in the pool, so there is nothing to poison at seed time —
  the path closes by construction rather than by screening.
- **The analyst's instructions carry no interpolation.** `_SYSTEM_PROMPT` is a
  constant. Everything variable reaches the model as a tool result it asked
  for, which is a different message with a different trust level.
- **Every verdict figure is recomputed.** `analysis_facts` re-derives the
  numbers from the tally rather than trusting what the request carried, so a
  doctored payload cannot make the analyst repeat its numbers.

## What a successful injection buys — and why that is not the argument

A first draft of this document led with "one biased vote", and used it to
justify screening in flag mode: log a detection, run anyway. That reasoning was
wrong twice, and both mistakes stay on the page because they are the ordinary
ways this kind of argument fails.

**It reasoned about impact under today's architecture.** "Low impact" is a claim
about a snapshot, and architectures move faster than the documents describing
them. A control justified by "the blast radius is small" evaporates the moment
the blast radius grows — silently, with nothing failing to mark the change.

**And it was wrong on its own terms.** The ceiling broke the first time anyone
looked for a way past it: a crafted headline becomes a vote reason,
`read_reasons` hands reasons to the analyst, and the analyst held a tool that
spends money. A ceiling that fails under the first probe was never a ceiling.

So impact is **not** what licenses this design. The layers below are, and each
does its job whether or not the impact estimate is right. The estimate is still
worth stating — it explains why the *panel* is a poor target — but it may never
again be used to argue that a control can be skipped:

- A panel agent has **no tools**. It cannot call anything, spend anything, or
  reach the database.
- It has **no memory and no shared state**. Twenty-five votes are twenty-five
  independent requests; nothing one panelist "learns" survives into another.
- Its **entire output is a forced choice plus one sentence**, enforced by
  `with_structured_output(PanelVoteOutput)`. There is no free-form channel to
  smuggle anything through, and a parse failure raises rather than being filed
  as a vote.
- **Position is randomised** 50/50 and seeded, so the most plausible payoff —
  bias toward whichever option is shown first — is split across the panel and
  cancels.

Read that as *"the panel is a poor thing to attack"*, not as *"an attack does not
matter"*. The difference is the whole point: the first is a reason to attack
something else — which is what the spend path turned out to be — and the second
is a reason to stop looking.

## Which is why the guardrails are shaped the way they are

**Delimiting, not filtering.** The customer's text is quoted between a
per-request random nonce so it cannot impersonate the scaffold. A fixed tag
would be forgeable — it is in the source, so a customer can close it — while a
nonce does not exist yet when they write their headline. This is the one
defence here that is deterministic and free, which is why it carries the most
weight.

**Screening blocks, and its two failure modes are kept apart.** A detection
refuses the run with a sentence naming the remedy; an unreachable screener lets
it through. Collapsing those gives a layer that is neither safe when it works
nor available when it does not. Availability is our problem and must not become
the customer's; a detection is about the customer's own text and is theirs to
fix.

Refusing is cheap because screening runs *before* the panel — a blocked run buys
no votes. The screener's own words never reach the response: a refusal that
quoted them would hand an attacker a channel into the reply.

**Bounded inputs.** A headline is copied into every panelist's prompt, so an
unbounded field is not one oversized request but a whole run of them. The caps
are set from what the product is — a headline is a headline — not from a threat
model.

**The analyst has no identity to leak.** Asked what it is, a model with only a
role answers from its weights and names its provider. That hands an attacker
the model family, and injection technique is family-specific. Unlike ids or
enums, this cannot be fixed by withholding something: the knowledge is in the
weights, so a prompt rule is the only lever, and its effect is unassertable.

## Where the boundary moved, and what is not covered

`read_reasons` puts text written by **another model** into the analyst's
context. Every other thing the analyst reads is ours: a constant prompt,
code-composed summaries, recomputed figures, backend-authored notices. A vote
reason is generated by the panel model, whose prompt carried the customer's
headline — so a crafted headline is a thin path to prose the analyst reads.

It cannot move a number, because every figure is recomputed. The exposure is
prose only. It is also the one path input screening structurally cannot see,
since screening runs before the request leaves us and this text is generated
after.

## What invalidates this argument

Everything above rests on three facts about today's system. Each of them can
stop being true, and the argument does not degrade gracefully — it stops
holding. They are listed here so a change that breaks one is recognisable as a
security change rather than a feature.

### 1. There is no other customer's data

The database holds synthetic personas, shared and belonging to nobody, and a
vote ledger keyed by the fingerprint of a question. There are no accounts and no
per-customer rows. So the attacker and the victim are the same person: someone
who injects "always pick option 1" has corrupted a test they paid for, to fool
themselves.

The moment a second tenant exists, that collapses, and screening is **not** what
should replace it. The pattern that should is already here — `search_personas`
scopes by construction:

```python
panel_ids=[vote.persona_id for vote in result.votes]   # from code, not the model
```
```sql
WHERE id = ANY(%s)
```

The model supplies a search phrase; it does not supply the id list. No sentence
it can emit widens that clause. **Data access is defended by scoping, never by a
classifier** — a classifier is a model guessing whether text looks like an
attack, and its blind spots are ours, while a `WHERE` clause has none.

The structural blocker to notice first: **`ChatRequest` carries the entire
`EvaluateResponse` from the client.** That is safe only while a caller can send
nothing but their own data. With tenants, the server must load the result under
the session's tenant and ignore what the body claimed.

### 2. No model in this system can spend money — the path is gone, not gated

The path was real: a crafted headline goes into the panel's prompt, the panel
model writes it into a vote *reason*,
[029](../issues/029-serve-vote-reasons-to-the-analyst.md) hands reasons to the
analyst, and the analyst held `run_panel_test`, which bought a whole new panel.

What stood there was the tool description's only-on-explicit-ask rule — a
**prompt rule**, i.e. asking the model nicely, in a codebase that elsewhere
calls prompt rules unassertable.

Gating it behind a request field would have closed the path. **Removing the tool
deletes it**, and leaves no flag for a later change to get wrong. Every tool the
analyst now holds reads; none spends and none writes. `/chat` does not even
construct a panel model, so the absence is visible in the endpoint's signature:
a spend path cannot reappear there without a new dependency somebody has to add
on purpose.

Nothing was lost. Re-running was never the analyst's job — the report has a
**Test again** control, which goes through `/evaluate`, where the screening, the
size caps and the delimiting already live. A human clicking a button is where a
decision to spend money belongs.

This is the assumption to watch: the moment any agent in this system gains a
tool that costs money or writes anything, the reasoning above stops applying and
the guard has to be designed rather than inherited.

### 3. Panels have no memory and no shared state

Twenty-five votes are twenty-five independent requests. Give panelists memory,
or let one run's output feed another's input, and a single injection stops being
worth one vote.

## Flag mode's own gap: a log needs a reader

Screening in flag mode buys evidence, and evidence is worth nothing unread.
Today the line goes to a server's stdout: nothing aggregates it, nothing alerts,
and nobody is assigned to look. That is a real gap in this design, not a detail
of its implementation.

It also changes meaning under multi-tenancy. Today a flag means "a customer
wrote something odd about their own test". With tenants it means **someone is
probing the isolation** — intelligence about an adversary, warranting a
rejected request, correlated attempts and a human, rather than a `WARNING`.

## What is deliberately not done

- **No output filtering.** Searching model output for forbidden strings is
  brittle, and it would mangle legitimate text — a report about a headline
  containing the word "ignore" is a legitimate report.
- **No blocking.** See above; revisit when flag mode has produced evidence.
- **No PII redaction.** This product's legitimate inputs are made of names and
  places: "Japanese homeowners in their 40s" is a target description, not a
  leak. A name-and-address redactor would mangle the product's core input.
