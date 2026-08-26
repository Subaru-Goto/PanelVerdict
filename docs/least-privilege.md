# What defends this product, and what would stop defending it

The security requirement asks for guardrails. Most of the defence here is not a
guardrail at all — it is the shape of the system. This is that argument written
down, so a change that quietly removes one of these reads as removing a defence
rather than simplifying a design.

It is deliberately organised around **what would make it false**. An assessment
that only says why things are safe today ages into a false sense of security the
moment the system moves, and nothing fails to announce it.

> **This document's stance is superseded — read it as history until
> [100/#209](https://github.com/Subaru-Goto/PanelVerdict/issues/209) rewrites it
> (author, 2026-08-25).**
>
> Everything below argues that injection is *tolerable* because the attacker and the
> victim are the same person. That protects the wrong asset. This deployment exists to
> **demonstrate competence**, and its visitors include people who will try to break it for
> that reason — their payoff is a screenshot, not a corrupted verdict, so "they only fooled
> themselves" defends nothing.
>
> Two consequences to assume are coming, rather than relying on the text below:
>
> - **Fail-open screening is very likely wrong**, on both channels. The stated trade — *"a
>   screening outage must not become a product outage"* — is backwards for a demonstration:
>   an outage embarrasses for an hour, a public injection embarrasses permanently.
> - **Enacted context ([094/#200](https://github.com/Subaru-Goto/PanelVerdict/issues/200))
>   adds a second channel that is *obeyed* rather than judged**, where position
>   randomisation cannot cancel (an instruction is applied to every panelist by design) and
>   delimiting cannot fence off text that is meant to be followed.
>
> What survives unchanged: the *mechanics* described below — where untrusted text enters,
> how the vote prompt is delimited, what the screener does and does not verify. It is the
> conclusion drawn from them that does not.

## The only untrusted input is the customer's own text

Five entry points. All of them the customer's own data, and that is the whole
attack surface a stranger controls:

1. **Two headlines.** The thing being judged. Nonce-fenced in the vote task's
   human turn, screened by `app/screening.py`'s copy policy.
2. **A target description.** Read by the translator into structured filters.
3. **The gate's edited `TargetQuery`.** Structured, validated by `PanelEdit`,
   which is deliberately narrower than `TargetQuery` so a caller cannot supply the
   report's own testimony about itself
   ([077 · #167](https://github.com/Subaru-Goto/PanelVerdict/issues/167)).
4. **The audience free text** ([094 · #200](https://github.com/Subaru-Goto/PanelVerdict/issues/200)).
   Rewritten by a model into one second-person instruction, and guarded by that
   same call: its structured output is an instruction *or* a refusal class, never
   both. A deterministic word-list backstop runs after it.
5. **The gate's edited instruction.** The one path where text reaches a panel
   prompt without passing the rewriter — the human's edit goes in as they left it,
   which is the point of the gate. So it is classified again on resume, by the
   same four rules, before a single vote is bought.

**Where 4 and 5 differ from 1–3, and why it is a considered exception.** The
approved instruction is rendered into every panelist's *system* prompt, not the
human turn — the only untrusted text in this codebase that does. It is there
because it is part of an identity rather than an object being judged, and identity
is what a system prompt holds. 095 measured the alternative: put beside the
headlines, in the block framed as the thing being judged, it costs the panel its
discrimination on exactly the pair an A/B test is made of. The fence and its frame
are what pay for the exception, and `app/screening.py` carries the note saying so.

Everything else that looks like it might be untrusted turns out not to be:

- **Personas are sampled or templated, never written by a model.** Every field
  comes from the OECD joint tables or the Big Five norms, and the prose a
  panelist reads is rendered from those numbers by `app/panel.py`. There is no
  LLM-authored content in the pool, so there is nothing to poison at seed time —
  the path closes by construction rather than by screening.
- **The analyst's instructions carry no interpolation.** `_SYSTEM_PROMPT` is a
  constant. Everything variable reaches the model as a tool result it asked
  for, which is a different message with a different trust level.
- **The verdict is recomputed.** `analysis_facts` re-derives `verdict` from the
  tally rather than trusting what the request carried, so a doctored payload
  cannot make the analyst repeat a fabricated probability.

  Precisely one figure, though, and the rest of `AnalysisFacts` is **not**
  protected this way: `tally`, `counts`, `polling`, `region_match` and `panel`
  are read off the request the client supplied. That is safe only while a caller
  can send nothing but their own data — the same assumption as §1 below, and it
  fails at the same moment.

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

*Note (2026-08-21):* this is about the model **family**, not about being an AI.
EU AI Act Art. 50(1) requires the opposite disclosure — a person interacting with
the analyst must be told it is artificial
([073](decisions/073-what-the-eu-ai-act-actually-requires.md),
[074 · #164](https://github.com/Subaru-Goto/PanelVerdict/issues/164)). The two
coexist: say *that* it is an AI system, never *which* one.

## Where the boundary moved, and what is not covered

`read_reasons` puts text written by **another model** into the analyst's
context. Every other thing the analyst reads is ours: a constant prompt,
code-composed summaries, recomputed figures, backend-authored notices. A vote
reason is generated by the panel model, whose prompt carried the customer's
headline — so a crafted headline is a thin path to prose the analyst reads.

It cannot move the verdict, which is recomputed. The exposure is prose only —
and it is the one path input screening structurally cannot see, since screening
runs before the request leaves us and this text is generated after.

It is also the one place the ticket's "delimiters around **all** interpolated
content" is not satisfied: `read_reasons` hands the analyst that prose as a bare
JSON tool result, undelimited. The vote prompt is delimited because that is
where a stranger's text enters; this is a second entry the ticket predates.

## What invalidates this argument

Everything above rests on three facts about today's system. Each of them can
stop being true, and the argument does not degrade gracefully — it stops
holding. They are listed here so a change that breaks one is recognisable as a
security change rather than a feature.

### 1. There is no other customer's data

The database holds synthetic personas, shared and belonging to nobody, and a
vote ledger keyed by the fingerprint of a question. **Corrected 2026-08-25:** there are
accounts now — [063/#158](https://github.com/Subaru-Goto/PanelVerdict/issues/158) keys the
request ledger on a verified subject id — so the tripwire this section describes has
fired rather than being scheduled. What remains true is that no table holds another
customer's *content*: the vote ledger is keyed by question fingerprint, not by owner. So the attacker and the victim are the same person: someone
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

Be precise about what that defends against, though: the ids are read from
`result.votes`, and `result` is the `EvaluateResponse` **the client posted**. So
the scope holds against the *model* and not against the *caller* — a client can
name any persona in the pool. Today those are the same party and the pool is
synthetic, so nothing leaks; the moment they are not, this is the first thing
that breaks, and it will break quietly because the code looks right.
[035](https://github.com/Subaru-Goto/PanelVerdict/issues/136) carries it.

The structural blocker to notice first: **`ChatRequest` carries the entire
`EvaluateResponse` from the client.** That is safe only while a caller can send
nothing but their own data. With tenants, the server must load the result under
the session's tenant and ignore what the body claimed.

*Note (2026-08-21):* this tripwire is now scheduled to fire. The next chapter's
definition of production-ready includes **authenticated and rate-limited**
([078 · #122](https://github.com/Subaru-Goto/PanelVerdict/issues/122)), so accounts
are on the map — which promotes everything this section prescribes (scoping by
construction, [035 · #136](https://github.com/Subaru-Goto/PanelVerdict/issues/136),
loading results server-side instead of trusting the posted body) from watch-item
to requirement of that work.

### 2. No model in this system can spend money — the path is gone, not gated

The path was real: a crafted headline goes into the panel's prompt, the panel
model writes it into a vote *reason*,
[029](https://github.com/Subaru-Goto/PanelVerdict/issues/130) hands reasons to the
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

## Screening's own gaps

**A detection is logged and nobody reads it.** The refusal protects the run; the
log line is the only record that an attempt happened at all, and today it goes
to a server's stdout — nothing aggregates it, nothing alerts, nobody is
assigned. Under multi-tenancy that stops being a nice-to-have: a detection would
then mean **someone is probing the isolation**, which is intelligence about an
adversary and warrants correlated attempts and a human, not a `WARNING`.

**Availability is a real bypass, and it is the deliberate one.** An unreachable
screener lets the run through, so anyone who can make the screener fail has
turned the control off. That is chosen — a screening outage must not become a
product outage — and it is the reason screening is the outermost layer rather
than a load-bearing one. The delimiting and the scoping do not fail open.

**The screener has no live verification.** Every test doubles it, deliberately,
because it is a paid model. So if the model ever stops satisfying
`with_structured_output`, every call raises, the fail-open path swallows it, and
the control is inert in production while the suite stays green. One manual run
with an obvious injection, checking for the 400, is what closes that — and
nothing automated will.

## What is deliberately not done

- **No output filtering.** Searching model output for forbidden strings is
  brittle, and it would mangle legitimate text — a report about a headline
  containing the word "ignore" is a legitimate report.
- **No format constraints, only size.** The ticket asked for "size/format
  limits" and only the size half shipped. A headline is free text in any
  language, so an allowlist would refuse real copy; if a format rule is ever
  added it needs a reason better than tidiness.
- **No PII redaction.** This product's legitimate inputs are made of names and
  places: "Japanese homeowners in their 40s" is a target description, not a
  leak. A name-and-address redactor would mangle the product's core input.

## What this document does not cover

Prompt injection is one boundary; **stored data is another**, and the two are
argued separately. Since Google sign-in shipped (063/#158) the shape of the
second one is:

- The tables this application writes hold an opaque subject id and nothing that
  could name a person. The address lives in the managed `auth.users` table —
  which is inside this project's own Postgres, not a vendor's, so access to that
  schema is part of this security surface rather than someone else's.
- Every table in `public` has row-level security on and no policies
  (`persistence.deny_data_api`). The browser holds a Supabase publishable key,
  and that key reaches the project's REST API; without this the whole schema —
  including the analyst transcripts the checkpointer stores — would be readable
  by anyone who opened a console on the site.
- OAuth tokens are never held: the provider keeps them.
