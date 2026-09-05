# Who the panel is

The report shows you the people who voted — their ages, where they live, what
they earn, and five personality traits each. This explains what those people are,
where they came from, and what they can and cannot tell you.

## Every panelist is invented

No human being answered anything. Every panelist is a synthetic persona: a set of
characteristics drawn from population statistics, handed to a language model, and
asked to choose between your two options.

This matters for how you read the result. The panel is not a survey of real
readers, and how they answer is not evidence of what real readers would do. What the
panel offers is a fast, cheap, repeatable reading of how two options land on a
described audience — useful for comparing them against each other, not for
estimating a click-through rate.

Nobody's data was collected, so nobody's privacy is at stake, and the same panel
can be asked again tomorrow and give the same answer.

<!-- Grounded in: `app/panel.py`; the report's own note that every voter is a sampled persona, not a person. -->

## Where the demographics come from

Age, gender, education and income are not invented one at a time. They are drawn
together from published national statistics, so the combinations that appear are
combinations that actually occur in that country's population — a panel does not
fill up with implausible people who each look fine in isolation.

That is why the panel can be described as representative of a population in a way
the personality traits cannot be.

<!-- Grounded in: `app/data/joint`, the OECD joint distribution tables; `docs/research/persona-seed-data.md`. -->

## What the five traits describe

Each panelist carries five personality traits, the set psychologists call the Big
Five. In plain terms:

- **Openness** — appetite for the new and unconventional, against a preference for
  the familiar and tried.
- **Conscientiousness** — how much someone plans, organises and thinks things
  through, against acting on impulse.
- **Extraversion** — how much someone is energised by people and the outside
  world, against preferring their own company.
- **Agreeableness** — how much someone is warm, trusting and accommodating,
  against being sceptical and blunt.
- **Neuroticism** — how readily someone worries and reacts to stress, against
  staying even under it.

These are dispositions, not verdicts. A low score is not a deficiency; it
describes a different way of reading the same thing.

<!-- Grounded in: `app/panel.py`, the trait level descriptions; `docs/research/persona-seed-data.md`. -->

## What a trait level says about one panelist

The report shows each trait as a level rather than a number, because the number on
its own says nothing a reader can use.

There are five levels, running **very low, low, medium, high, very high**. Five
rather than three because three cannot express the range the panel actually draws
from: two people some distance apart would render as the same word, which flattens
what each of them is told to be.

A level is a statement about **where this panelist sits relative to the
population**, not an absolute quantity. Someone shown as high in openness is more
drawn to novelty than most people are; someone shown as low leans the other way, to
the familiar and the tried. Each trait in the list above reads the same way — the
level says how far toward one of its two poles this person sits, compared to
everybody else.

It does not mean they are adventurous in some fixed sense, and it does not
translate into a score on any questionnaire anyone has taken.

Read a level as the sentence the panel would use to introduce that person, which
is exactly what it is: it is turned into a phrase and put into the prompt that
panelist votes from. So a level is not a label attached after the fact — it is part
of what the panelist was told they are before they saw anything.

<!-- Grounded in: `app/panel.py`, `_TRAIT_PHRASES`. -->

## What the traits are conditioned on, and what that rules out

Traits are drawn around a population average that depends on **age and gender
only**.

That is a deliberate limit and it rules out a whole class of reading. A panelist's
openness carries no claim about their country, their education, or their culture,
because none of those went into the draw. If a panel drawn in one country shows
higher openness than a panel drawn in another, that is the ages and genders that
happened to be sampled, and nothing about the two nations.

The traits also vary together rather than independently, the way they do in the
published data, so a panelist's five traits form a combination that occurs in
people rather than five unrelated dice rolls.

<!-- Grounded in: `app/bigfive.py` — *"country does not condition the Big Five μ"*; Donnellan & Lucas, cited in `docs/research/persona-seed-data.md`. -->

## What this panel has been validated on, and what it cannot tell you

The honest limit, stated because it bounds every verdict on the report.

Deliberately specific about what was tested, because the limit is about the
evidence and not about the arithmetic.

The panel has been validated on **written headlines** that say genuinely different
things, and it separates them. It has **not** been shown to track human preference
between two headlines that say the *same* thing in different words — and that
second case is what a lot of real copy testing is.

Everything else on this page — how the answer is decided, what the tie zone is,
what a panelist is — holds whatever is being compared, because none of it depends
on the options being text. This paragraph does not. What the panel has been
measured on is headlines, so a verdict on anything else is unvalidated in a way the
report cannot flag for you.

So a clear lead between two options that say genuinely different things is the case
this product has evidence for. A clear lead between two rephrasings of one idea
is the case where the panel may be confidently wrong, and the report should be
read as one input rather than as an answer.

<!-- Grounded in: `docs/research/task-framing.md`; the *Known limitations* section of the project README. -->
