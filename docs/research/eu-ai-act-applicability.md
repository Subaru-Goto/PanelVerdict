# EU AI Act — what actually applies to PanelVerdict?

Answers the question: **which obligations of Regulation (EU) 2024/1689 (the "AI Act")
apply to PanelVerdict, and does anything in it require logging/tracing each LLM step?**

All sources read **live, 2026-08-21**. Quotes are verbatim; anything labelled
*inferred* is this document's own reasoning over those quotes, not a regulator
statement. **This is a technical/regulatory read by an engineer, not legal advice.**

Sourcing note: EUR-Lex itself was unreachable from this environment (CloudFront WAF
challenge on every request), so article text of 2024/1689 was retrieved from the
[AI Act Explorer](https://artificialintelligenceact.eu/) (Future of Life Institute),
which mirrors the Official Journal text per article, and cross-checked where possible
against the European Commission's own Article 50 guidelines
(**C(2026) 5054 final, 20.7.2026**, PDF downloaded from
[digital-strategy.ec.europa.eu](https://digital-strategy.ec.europa.eu/en/library/guidelines-transparency-obligations-providers-and-deployers-ai-systems)),
which quote and interpret the same articles. Facts that could only be confirmed via a
secondary source are explicitly flagged.

The product, as verified in this repo: a synthetic-panel A/B tester for marketing
headlines. Two headlines + an audience description go in; an LLM pipeline selects
synthetic personas, each casts one LLM vote with a short reason, a Bayesian verdict
comes out, and an "analyst" chatbot answers follow-up questions about the run. Solo
developer, public demo, possibly EU users. Models are OpenAI models via OpenRouter
(consumed over API). The report UI already discloses that panelists are synthetic.

## Bottom line for PanelVerdict

1. **Not high-risk, not prohibited.** Nothing in Annex III or Article 5 covers
   synthetic-audience copy testing. PanelVerdict is a minimal-risk system that
   happens to fall under Article 50 transparency.
2. **Article 50(1) applies to the analyst chatbot** (and arguably the whole
   interactive flow): users must be explicitly told they are interacting with an AI
   system, in-context, at the latest at first interaction. The existing "panelists
   are synthetic" disclosure is *not* sufficient on its own — the Commission
   guidelines say generic or capability-only statements don't satisfy it.
3. **Article 50(2) (machine-readable marking of AI-generated text) plausibly applies**
   to the generated text PanelVerdict shows (vote reasons, report prose, chatbot
   answers), because the solo dev is the *provider* of a generative AI system. This
   is the least crisp obligation for a text-only in-app product; the guidelines
   allow proportionate, state-of-the-art-limited solutions, and there is a voluntary
   Code of Practice. **Article 50(4)** (labelling text that informs the public) does
   **not** apply — per-user chatbot/report output is expressly out of scope.
4. **Article 12 record-keeping does not apply.** It is high-risk-only, and even
   there it requires *event*-level logs (periods of use, risk-relevant situations),
   not per-LLM-call traces.
5. **No provision anywhere in the Act requires per-step LLM traceability for this
   product.** Any run-tracing PanelVerdict builds is an engineering choice, not a
   legal duty.
6. **Timing:** Article 50 has applied since **2 August 2026** — i.e. it is in force
   *now*. High-risk (Annex III) obligations were deferred by the Digital Omnibus
   (Regulation (EU) 2026/1744) to **2 December 2027** and are irrelevant here anyway.
   The concrete to-do list is three small UI/copy changes (§6).

---

## 1. Risk classification: minimal risk, confirmed

**Prohibited practices (Article 5, applies since 2 February 2025).** The two
candidates that even sound close are 5(1)(a) and 5(1)(b):

> "the placing on the market, the putting into service or the use of an AI system
> that deploys subliminal techniques beyond a person's consciousness or purposefully
> manipulative or deceptive techniques, with the objective, or the effect of
> materially distorting the behaviour of a person or a group of persons by
> appreciably impairing their ability to make an informed decision, thereby causing
> them to take a decision that they would not have otherwise taken in a manner that
> causes or is reasonably likely to cause that person, another person or group of
> persons significant harm"
> — Article 5(1)(a), read 2026-08-21 via
> [AI Act Explorer](https://artificialintelligenceact.eu/article/5/)

*Inferred:* PanelVerdict deploys no technique on any natural person — the "panel" is
synthetic, the only natural person involved is the marketer reading a report — and
nothing distorts their behaviour or causes significant harm. 5(1)(b)
(exploiting vulnerabilities of age/disability/social situation) fails for the same
reason. Points (c)–(h) (social scoring, predictive policing, face scraping, emotion
recognition at work/school, biometric categorisation, real-time remote biometric ID)
are categorically off-topic. The Commission's interpretive guidance on Article 5 is
the Guidelines on prohibited AI practices, **C(2025) 5052 final** (cited as such,
dated Brussels 29.7.2025, in footnotes 8 and 12 of C(2026) 5054 final).

**High-risk (Article 6(2) + Annex III).** The Annex III areas are: 1. biometrics;
2. critical infrastructure; 3. education and vocational training; 4. employment and
workers management; 5. essential private/public services (incl. creditworthiness,
insurance pricing, emergency dispatch); 6. law enforcement; 7. migration/asylum/
border control; 8. administration of justice and democratic processes (list read
2026-08-21 via [AI Act Explorer, Annex III](https://artificialintelligenceact.eu/annex/3/)).
Marketing copy testing appears in none of them. The only near-miss is point 8(b):

> "AI systems intended to be used for influencing the outcome of an election or
> referendum or the voting behaviour of natural persons in the exercise of their
> vote…" — Annex III point 8(b), read 2026-08-21

*Inferred:* classification under 8(b) turns on *intended use*. PanelVerdict's
intended purpose is marketing-headline testing, so it is not high-risk. If the demo
were ever pitched at political-campaign message testing, this point would need a
fresh look — flagging that as the one real classification edge.

**Conclusion: minimal-risk AI system, subject only to the Article 50 transparency
regime (§2) and horizontal provisions (§4).** The Commission guidelines confirm the
category exists: "AI systems can also fall within the scope of Article 50 AI Act
without being classified as high-risk pursuant to Article 6 AI Act"
(C(2026) 5054 final, para. 25).

## 2. Article 50 transparency

Article 50 full text read 2026-08-21 via
[AI Act Explorer](https://artificialintelligenceact.eu/article/50/); interpretation
from the Commission **Guidelines on the implementation of the transparency
obligations for certain AI systems under Article 50** (C(2026) 5054 final, adopted
20.7.2026, PDF retrieved 2026-08-21 from the Commission's
[library page](https://digital-strategy.ec.europa.eu/en/library/guidelines-transparency-obligations-providers-and-deployers-ai-systems),
document 131215).

### 2a. Article 50(1) — the "you are talking to an AI" duty. Applies.

> "Providers shall ensure that AI systems intended to interact directly with natural
> persons are designed and developed in such a way that the natural persons concerned
> are informed that they are interacting with an AI system, unless this is obvious
> from the point of view of a natural person who is reasonably well-informed,
> observant and circumspect, taking into account the circumstances and the context
> of use." — Article 50(1)

The guidelines' in-scope examples include exactly this product shape: "AI-enabled
voice assistants, chatbots/conversational agents in various contexts (e.g. public
service, customer support, complaints management, e-commerce, finance, healthcare,
education etc.)" (para. 31 examples), and among systems that **fail** the
obviousness exception: "AI chatbots embedded in online platforms or assistance
support tools (helpdesks) whereby users directly interact and receive AI outputs
(e.g. replies to queries or other AI-generated content) they may perceive as
human-generated" (§3.2.1 examples). Even a one-shot exchange counts: "The
interaction may be a one-time exchange (e.g. single prompt followed with a single
reply) or take place over a certain period time (multi-turn)" (para. 30.ii) —
*inferred:* the headline-submission → report flow is itself likely in scope, not just
the chatbot.

**Can PanelVerdict rely on the "obvious" exception?** Probably not, and it isn't
worth the argument. The guidelines say the exception "should be interpreted
restrictively" and "should be limited to cases where there is almost no doubt left
about the nature of the interaction for an average person from the targeted and
reasonably foreseeable audience" (para. 45). A public demo is general-public-facing;
the professional-audience carve-outs (e.g. "AI-powered code assistance and code
review chatbots available only to professional developers") assume access
restriction PanelVerdict doesn't have. *Uncertain:* a reasonable person could argue
a tool whose whole premise is "synthetic panel" makes AI-ness obvious — but since
para. 40 also requires disclosure "in all situations where the AI system is being
asked questions relating to its nature", the safe and cheap move is to disclose.

**What exactly must be disclosed and how.** The substance is "the artificial,
non-human nature of the interacting counterpart" (para. 35). Adequate techniques
include "Prominent, plain-language labels or banners (e.g. 'You are interacting with
an AI system') and first-turn greetings in chatbots" positioned "close to the
interaction interface (e.g. near the input/output field)" (para. 37). Explicitly
**insufficient** (para. 38): disclosures only in terms and conditions; machine-
readable marks not perceivable at the point of interaction; "generic references to
'assistant'"; generalised disclosures ("Services on this website use AI"); and
"statements solely referring to underlying technologies (e.g. 'this system uses
LLMs')". Timing/format: "in a clear and distinguishable manner at the latest at the
time of the first interaction or exposure" and accessible (Article 50(5)). "A
single, prominent notification before the first interaction … is likely to suffice
in most instances" (para. 40).

### 2b. Article 50(2)/(4) — marking of synthetic content

**Article 50(4), second subparagraph (labelling AI text) — does NOT apply.** It only
covers "text which is published with the purpose of informing the public on matters
of public interest". The guidelines' out-of-scope examples fit PanelVerdict twice
over: "News summary generated by a chatbot that is only available to the user that
prompted the chatbot" and "AI-manipulated text that is part of a company's
advertisement or product descriptions (not including any claims related to e.g.
health, consumer safety or sustainability)" (§6.2.1 examples). Per-user report and
chat output is not "published", and headline copy is advertising. (Also: 50(4) is a
*deployer* duty; if a marketing agency used PanelVerdict output in public-interest
editorial text, that would be *their* duty, with the human-review/editorial-
responsibility exemption in §6.2.3.)

**Article 50(3)** (emotion recognition / biometric categorisation) — N/A, no
biometrics. **Deep fakes (50(4) first subparagraph)** — N/A: a 'deep fake' is
content "that resembles existing persons, objects, places, entities or events and
would falsely appear to a person to be authentic or truthful" (Article 3(60));
synthetic personas presented *as* synthetic resemble no existing person.

**Article 50(2) (machine-readable marking + detectability) — plausibly applies, and
is the fuzziest part.**

> "Providers of AI systems, including general-purpose AI systems, generating
> synthetic audio, image, video or text content, shall ensure that the outputs of
> the AI system are marked in a machine-readable format and detectable as
> artificially generated or manipulated. Providers shall ensure their technical
> solutions are effective, interoperable, robust and reliable as far as this is
> technically feasible, taking into account the specificities and limitations of
> various types of content, the costs of implementation and the generally
> acknowledged state of the art…" — Article 50(2)

*Inferred:* PanelVerdict generates synthetic text shown to users, and the solo dev
is its provider (§4), so the conditions in guidelines para. 56 are met. What the
guidelines give and take away:

- Out of scope: "Outputs generated in the form of a short sequence of numbers,
  symbols or letters (e.g. single words, image captions, alt-text, UI labels…)"
  (para. 68) — *inferred:* the verdict numbers and vote tallies are not "synthetic
  text"; the prose (vote reasons, report narrative, chatbot answers) is.
- Out of scope: agent internals — "intermediate processing steps such as reasoning
  and chain of thought" that are not perceived by natural persons (para. 63). The
  targeting/query steps of the pipeline need no marking; only user-visible text does.
- The B2B/industrial no-marking carve-out (para. 87) explicitly excludes "public and
  consumer-facing AI systems", so a public demo can't use it.
- Proportionality is real: "the costs of implementation of certain technical
  solutions … may be disproportionate to marginal gains" (para. 85), and providers
  need not keep provenance chains (para. 73). Recital 133-listed techniques include
  "watermarks, metadata identifications, cryptographic methods…, logging methods,
  fingerprints or other techniques, and a combination of such techniques" (quoted at
  para. 73).
- A voluntary **Code of Practice on Transparency of AI-generated Content** (final
  version published 10 June 2026;
  [Commission page](https://digital-strategy.ec.europa.eu/en/policies/code-practice-ai-generated-content),
  read 2026-08-21) is the sanctioned way to "demonstrate compliance with the marking
  and detection obligations" (guidelines para. 84, per Article 50(7)).

*Was uncertain, now read (075/#165, 2026-09-05):* the paragraphs below record what
the final Code actually asks of a text-only provider, what this product emits, and
what was decided. The posture above — keep the visible "synthetic panel" labels,
metadata-mark any exportable artefact if one ever exists — stands.

#### The Code of Practice baseline for text (final Code, read 2026-09-05)

Source: *Code of Practice on Transparency of AI-generated Content*, final version
published 10 June 2026
([Commission page](https://digital-strategy.ec.europa.eu/en/policies/code-practice-ai-generated-content);
[PDF](https://ec.europa.eu/newsroom/dae/redirection/document/129555), 38 pages, text
extracted locally). Assessed **adequate** under Article 50(7) by the Commission and the
AI Board; ~190 signatories including OpenAI, Google, Anthropic, Mistral and Microsoft,
"about half … small and recent companies"; open for signature
([Commission news, 31 July 2026](https://digital-strategy.ec.europa.eu/en/news/strong-backing-code-practice-transparency-ai-generated-content)).
Voluntary: signatories "rely on its measures to demonstrate compliance"; a
non-signatory shows adequacy on its own. The Guidelines cited throughout this record
are the final version, C(2026) 5054 final, adopted 20 July 2026 (see §1; the
Commission library lists it as document 131215).

What Section 1 (providers, Article 50(2)) requires for **text**, quoted:

- **Two kinds of text, two rules.** For *free-form* text one layer suffices, and it is a
  watermark: "Given that free-form text cannot transport metadata, a single-layer of
  marking as described in Sub-measure 1.1.2 is considered sufficient to comply with the
  requirements of Article 50(2) AI Act for this specific type of content" (Measure 1.1).
  Sub-measure 1.1.2: "Signatories will ensure that AI-generated or manipulated content
  is marked with an imperceptible watermark, **with the exception of very short text**.
  For free-form text longer than 200 tokens, watermarking still needs to be applied,
  even though it may have lower reliability." It names "post-hoc watermarking" and
  "model watermarking" as the two strategies; model providers are *encouraged* to do
  the latter. For *containerised* text — glossary: "text inside PDFs, Word documents, or
  HTML files" — Measure 1.1 asks two layers, and Sub-measure 1.1.1 is the first: "If
  content is generated, manipulated **or exported** in a data format that supports
  attaching metadata (e.g., an audio, image, video, or containerised text),
  Signatories will record information in the metadata on whether the content is
  AI-generated or manipulated. All recorded information will be digitally signed and
  time-stamped … in a secure and tamper-evident manner."
- **"Very short text" is defined, in tokens.** Glossary: "Text that is so short that in
  many cases it cannot be watermarked, even with a basic level of reliability. At the
  time of publication of the code, state-of-the-art techniques enable watermarking …
  of text as short as 200 tokens, with the expectation that this threshold will
  decrease as new methods become available. Until then, 'very short text' should be
  understood as **text shorter than 200 tokens**."
- Fingerprinting or logging is **optional** (Sub-measure 1.1.3). Detection access "may be
  restricted" where "only a limited number of natural persons will be exposed …
  (e.g., AI systems in professional settings)" (Sub-measure 2.1.2) — a detection rule,
  not a marking exemption.
- **SME proportionality is process, not marking.** Preamble (g): "simplified ways of
  compliance for SMEs and SMCs, including startups, should be possible, in a
  proportionate manner"; operationalised only as "implemented in a proportionate
  manner" on the compliance-process, training and literacy measures (2.4, 4.1, 4.3).
  Nothing loosens Sub-measure 1.1.2 for a small provider.
- **Downstream providers.** Model providers are "encouraged" — not bound — "to
  implement watermarking at the model level … to facilitate compliance of downstream
  providers" (1.1.2); a downstream provider "may rely on the results of testing
  performed by an upstream model provider" (Measure 4.2). Nothing in the Code makes a
  downstream provider able to watermark text its upstream does not.

**Transitional note — corrected.** Regulation (EU) 2026/1744 of 8 July 2026 (Digital
Omnibus on AI; OJ L, 24.7.2026; in force the third day after publication, Article 46
— [EUR-Lex ELI](https://eur-lex.europa.eu/eli/reg/2026/1744/oj), read 2026-09-05)
states the intent in recital 38: "a transitional period of four months for providers
who have already placed their systems on the market before the 2 August 2026". The
operative text is a new Article 111(4) AI Act: "Providers of AI systems … generating
synthetic audio, image, video or text content, **that have been placed on the market
before 2 August 2026** shall take the necessary steps in order to comply with
Article 50(2) by 2 December 2026" (*secondary*: quoted from
[AI Act Explorer, Art. 111](https://artificialintelligenceact.eu/article/111/), read
2026-09-05 — EUR-Lex's HTML truncates before the operative articles, so the article
text is not verified against the OJ; the recital is).

*Inferred:* PanelVerdict was placed on the market (Article 3(9): first made available
on the Union market) no earlier than **2026-08-23**, the date its deploy artefacts
(`backend/Dockerfile`, `docs/deploy.md`) first landed in git — a lower bound, since
nothing could have been served before they existed, and there is no record of a
public URL before that. That is after the 2 August 2026 cut-off, so **the four-month
transition does not apply, and Article 50(2) has bound this product from the day it
went live.** The 2026-08-21 reading of "plausible breathing room" was wrong for this
product.

#### What this product emits, measured (2026-09-05)

Every reader-facing token is generated by `openai/gpt-5.6-luna` (panel votes, the
analyst, the audience rewrite). OpenAI signed the Code but ships **no text watermark**
in any GPT model or API as of August 2026 (*secondary source*:
[layer3labs guide, 22 Aug 2026](https://www.layer3labs.io/guides/does-chatgpt-watermark-text),
which reads OpenAI's [provenance page](https://openai.com/index/advancing-content-provenance/)
as covering images and audio only; that page was not readable from here and is not
quoted directly). So there is no upstream mark to rely on. Post-hoc text
watermarking, which the Code names as a strategy, was not evaluated for this product
— recorded as untested, not as impossible.

| output | measured | under the Code |
|---|---|---|
| a panelist's vote reason | 300 reasons across the three demo captures: median ~20 tokens, max 31 (`tiktoken` o200k_base) | very short text — **exempt** |
| the audience instruction shown in the panel gate | bounded at `MAX_INSTRUCTION_CHARS` = 400 chars | very short text — **exempt** |
| an analyst reply | 49–231 *visible* tokens across the six measured turns (output minus reasoning, [analyst-turn-cost.md](analyst-turn-cost.md); 212, 174, 57 at default effort, 231, 117, 49 at low); completion cap 2,048 | **some cross 200 tokens → in scope, and not marked** |
| the stored report (`tests.report`, JSON) | one row per kept run, reopenable by its owner; no export surface exists | a *container* — Sub-measure 1.1.1's metadata layer applies to it, whatever is displayed |

#### Decision (author, 2026-09-05)

- **Record the gap; do not sign.** Analyst replies over 200 tokens are within Article
  50(2), and marking them is not technically feasible for this product: free-form text
  takes only a watermark, a watermark is applied inside the model, and the model
  provider does not apply one. Article 50(2) binds "as far as this is technically
  feasible, taking into account … the costs of implementation and the generally
  acknowledged state of the art", and the Code's own glossary concedes the threshold.
  Signing the Code would commit to Sub-measure 1.1.2, which this product cannot
  perform — a promise it cannot keep is worse than a stated gap.
- **Ask for brevity, by construction.** The analyst's system prompt now asks for every
  reply to stay under 150 words — about 200 tokens at the ratio measured on the prompt
  itself, 5,794 chars / 1,271 tokens ≈ 4.6 chars a token. This is an *ask*: a prompt
  rule is unassertable by the suite (025 routes doubles through the tools), and a hard
  cut-off mid-sentence is the failure 090/#276 fixed, so no cap enforces it. The
  reason is kept in a code comment, not in the rule the model reads — told to the
  model, it becomes machinery the reader may be told about. A test pins that the ask
  is made and that it yields to a decline, a caveat or a "too few to say".
- **Mark the stored report.** The ticket's *Done when* names *persisted* artefacts, and a
  stored report is containerised text under Sub-measure 1.1.1, displayed or not. Every
  report now carries a server-written `provenance` block — `ai_generated: true`, the
  generating model, `text_marking: "none"`, and when it was recorded — optional on
  read so rows kept before it load unchanged (the move `timings` made in 033). The
  block says what is true: the container is marked, the prose inside it is not. **Not
  done:** the digital signing and timestamping 1.1.1 also asks for, which is a key
  infrastructure this product does not have — recorded as the remaining gap for this
  layer.
- **The 50(4) argument does not reach 50(2).** The ticket's scope note excluded in-app
  text on the strength of the Guidelines' 50(4) examples ("only available to the user
  that prompted"). That exclusion is about *labelling published text*; the 50(2)
  marking duty attaches to the generated text itself, displayed or stored. The
  exemptions that actually apply here are the Code's own: very short text, and
  internals.
- **What is deliberately NOT marked, with its source:** vote reasons and the audience
  instruction, because both are "very short text" under the Code's 200-token definition
  above; the pipeline's internals, because the Guidelines put "intermediate processing
  steps" out of scope (para. 63); and the prose of analyst replies over 200 tokens,
  because no marking is available to this product (above).
- **Reopen when** OpenAI (or whichever provider the analyst runs on — the tripwire in
  `tests/test_config.py` names the setting) ships text watermarking with a detection
  API; or the Code's 200-token threshold moves at a review (the Code is updated "at
  least every 2 years" —
  [Commission FAQ](https://digital-strategy.ec.europa.eu/en/faqs/code-practice-transparency-ai-generated-content),
  read 2026-09-05); or an export surface is built, which would owe the signing.

## 3. Article 12 record-keeping: high-risk only — and not per-step tracing even then

> "High-risk AI systems shall technically allow for the automatic recording of
> events (logs) over the lifetime of the system." — Article 12(1), read 2026-08-21

The whole of Chapter III Section 2 (Articles 8–15), including Article 12, applies
**only** to high-risk AI systems; PanelVerdict is not one (§1), so Article 12 does
not apply, full stop.

Even if it did, the granularity is *events*, not LLM calls:

> "In order to ensure a level of traceability of the functioning of a high-risk AI
> system that is appropriate to the intended purpose of the system, logging
> capabilities shall enable the recording of events relevant for: (a) identifying
> situations that may result in the high-risk AI system presenting a risk within the
> meaning of Article 79(1) or in a substantial modification; (b) facilitating the
> post-market monitoring referred to in Article 72; and (c) monitoring the operation
> of high-risk AI systems referred to in Article 26(5)." — Article 12(2)

The only place the Act prescribes concrete log fields is Article 12(3), and it is
limited to remote-biometric-identification systems (period of each use, reference
database, input data, identity of verifying humans). Retention, where applicable, is
Article 19(1): providers keep automatically generated logs "to the extent such logs
are under their control … for a period appropriate to the intended purpose of the
high-risk AI system, of at least six months". None of this reaches PanelVerdict.

## 4. Deployer vs provider: the solo dev is a (downstream) *provider* of a minimal-risk AI system

Definitions (Article 3, read 2026-08-21):

> "'provider' means a natural or legal person … that develops an AI system or a
> general-purpose AI model or that has an AI system or a general-purpose AI model
> developed and places it on the market or puts the AI system into service under its
> own name or trademark" — Article 3(3)

> "'deployer' means a natural or legal person … using an AI system under its
> authority except where the AI system is used in the course of a personal
> non-professional activity" — Article 3(4)

*Inferred, with strong support from the guidelines:* relative to OpenAI's models the
dev is a downstream API consumer, but relative to **PanelVerdict the AI system** the
dev *develops it and puts it into service under their own name* — that is the
provider role, "whether for payment or free of charge" (guidelines para. 10). The
guidelines' own example nails the public-demo case: "a company provides a generative
or interactive AI application (e.g. a chatbot, image generator, AI agent) on the
Union market under its own name or trademark … The company is a provider responsible
for compliance with the transparency obligations in Article 50(1) and/or (2) AI Act,
regardless of whether the AI system is provided for free or for payment" (para. 11
example). The guidelines call this actor the "downstream AI system provider"
(para. 27). GPAI-model obligations (Chapter V) stay with OpenAI: "Article 50 AI Act
does not explicitly apply to GPAI models" (para. 27). Article 25's
deployer-becomes-provider mechanics are high-risk-only ("shall be considered to be a
provider of a **high-risk** AI system", Article 25(1)) and don't bite here.

Note the *personal non-professional* exclusion (Article 2(10)) does not help: a
public demo, even unpaid, is treated as professional/provider activity (guidelines
paras. 19–20). The open-source exclusion (Article 2(12)) also expressly carves
Article 50 back in: the Act doesn't apply to free and open-source AI systems
"unless they are placed on the market or put into service as high-risk AI systems or
as an AI system that falls under Article 5 or 50" — so open-sourcing PanelVerdict
would not shed the Article 50 duties.

**Full obligation set for a minimal-risk system provider:** Article 50(1), (2) and
(5) transparency; avoid Article 5 practices; AI literacy under Article 4
(originally: "Providers and deployers of AI systems shall take measures to ensure,
to their best extent, a sufficient level of AI literacy of their staff…" — trivially
satisfied by a solo dev; *uncertain:* the Digital Omnibus softened/shifted this
duty — the Commission's proposal summary says it would "requir[e] the Commission and
the Member States to foster AI literacy instead [of] enforcing unspecified
obligation on providers and deployers"
([EP OEIL procedure summary 2025/0359(COD), 19/11/2025](https://oeil.europarl.europa.eu/oeil/en/procedure-document-summary/pdf?id=1866801),
read 2026-08-21); final adopted wording not verified). Voluntary codes of conduct
(Article 95) are exactly that — voluntary. That's the entire list. No conformity
assessment, no registration, no technical documentation, no logging.

## 5. Timeline and penalties, as of 2026-08-21

Application dates, per the Commission's AI Act policy page
([digital-strategy.ec.europa.eu](https://digital-strategy.ec.europa.eu/en/policies/regulatory-framework-ai),
read 2026-08-21), reflecting the **Digital Omnibus on AI (Regulation (EU) 2026/1744,
in force 27 July 2026)**:

| Provision | Applies from |
|---|---|
| Prohibitions (Art. 5), AI literacy (Art. 4) | 2 February 2025 |
| GPAI-model rules, governance, penalties framework | 2 August 2025 |
| **Article 50 transparency** | **2 August 2026 — in force now.** "The transparency rules of the AI Act will come into effect in August 2026." |
| High-risk, Annex III | **2 December 2027** (deferred by Omnibus): "Rules for systems used in certain high-risk areas — including biometrics, critical infrastructure, education, employment, migration, asylum and border control — will apply from 2 December 2027." |
| High-risk embedded in Annex I products | **2 August 2028**: "For systems integrated into products such as lifts or toys, the rules will apply from 2 August 2028." |

Penalties (Article 99, read 2026-08-21): prohibited practices — "up to 35 000 000
EUR or, if the offender is an undertaking, up to 7 % of its total worldwide annual
turnover for the preceding financial year, whichever is higher"; non-compliance with
listed operator obligations **including Article 50** — "up to 15 000 000 EUR or …
up to 3 % of its total worldwide annual turnover…"; supplying incorrect/misleading
information — "up to 7 500 000 EUR or … up to 1 %…". For SMEs each cap is read as
the *lower* of the amount/percentage. *Inferred:* fines are maximums scaled by
gravity; for a solo dev the realistic exposure for an Article 50 miss is an order to
comply, but the tier it sits in is the 15 M€/3 % one.

## 6. Is there ANY per-step LLM traceability requirement? No. What to change instead

**No provision of Regulation 2024/1689 requires PanelVerdict to log or trace
individual LLM steps.** The only logging article (12, plus 19/26(6) retention) is
high-risk-only (§3), and even the Article 50(2) marking discussion expressly says
"providers are not required to record or keep a full provenance chain" (guidelines
para. 73) and that agent "reasoning and chain of thought" is not even content in
scope (para. 63). Run-tracing in this repo remains purely an engineering/debugging
decision.

What Article 50 *does* imply, concretely and small:

1. **Chatbot + submission flow disclosure copy** (Art. 50(1)+(5)): a plain, visible
   line at the point of interaction, before/at first exchange — e.g. a first-turn
   analyst greeting and a persistent label near the input: "You are chatting with an
   AI system." Not only in a footer, not only in T&C, not "powered by LLMs". Also
   make sure the system self-discloses if a user asks "are you human?" (para. 40).
2. **Keep and sharpen the synthetic-panel disclosure** (already present in the
   report UI) — it serves Art. 50(1) context but does not replace the explicit
   AI-interaction notice.
3. **Machine-readable marking of generated text where feasible** (Art. 50(2)):
   metadata-tag exported/rendered reports as AI-generated (e.g. HTML `meta`/JSON
   field on report artefacts), watch the
   [Code of Practice on Transparency of AI-generated Content](https://digital-strategy.ec.europa.eu/en/policies/code-practice-ai-generated-content)
   for the eventual text-marking baseline. This is the one item marked *uncertain*
   in practice (§2b) — proportionate effort, documented reasoning, and code-of-
   practice tracking is the defensible posture.

Nothing else. No registration, no conformity assessment, no logging mandate, no
technical file.
