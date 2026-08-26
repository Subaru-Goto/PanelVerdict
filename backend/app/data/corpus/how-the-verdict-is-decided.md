# How the verdict is decided

This explains what the report's answer means and how it was reached. Every number
you need is on the report itself — this page is about what those numbers are
*for*.

## What the panel is actually measuring

Each panelist is shown both of your options and is asked one question about them.
Today that question is which of the two they prefer. Half of them see your first
option first, so a habit of picking whatever comes first cannot disguise itself as
a real choice.

What comes out of that is a share: out of everyone who voted, how many chose B.
That share is the whole measurement. It is not a score, a rating, or a prediction
of clicks — it is the fraction of a synthetic panel that went one way when asked.

Everything else on this page is about that share and holds whatever the question
is. Only this paragraph names it.

## Why the answer is a range and not one number

The share you would get is not the share you would get again. Ask a different
panel of the same size and you would get a slightly different number, the way two
polls of the same electorate disagree.

So the report gives a **credible interval**: a range, with a stated probability
that the true share for a panel like this one falls inside it. Read it exactly
that way — "there is that much probability the real share is in here". That is a
plainer thing than the confidence interval you may have met in a statistics class,
which is a statement about the procedure rather than about this particular answer.

A wide interval means the panel did not buy much certainty. A narrow one means it
did. The width comes from how many people voted, and it narrows slowly: buying
twice the confidence costs far more than twice the panel.

<!-- Grounded in: `app/verdict.py`, `posterior` — a Beta-Binomial posterior over the share preferring B, with a flat prior. -->

## The tie zone, and why there is one

Some differences are real and still not worth acting on. If one option is
very slightly ahead, forever, that is a fact about the world and a waste of your
afternoon.

So the report carries a band around dead even — a zone of differences small enough
that we are willing to call them equivalent in practice. Its width is on the
report, and it was chosen deliberately rather than derived: it encodes what size
of difference is worth acting on, which is a judgement about your decision, not
something the arithmetic can hand you.

Two things pinned the width. Narrower, and no panel anyone would pay for could ever
gather enough probability inside it, so "these are equivalent" would have been an
answer the product could never give. And the band sits inside the panel's own
run-to-run wobble — the amount the same panel's answer moves when nothing about
the options has changed. Calling a difference that small a tie is honesty rather
than laxity.

<!-- Grounded in: `app/verdict.py`, `_ROPE` and `rope_verdict`; `docs/research/adaptive-stopping.md`. -->

## Why being ahead is not the same as a clear lead

This is the question the report is most often asked, and the answer is the whole
method in one line: **the report answers with a probability, and being ahead in the
count is not a probability.**

One option can hold the larger share while it is still quite possible that the two
are equivalent. So the report does not ask which is ahead; it asks how much of the
probability sits beyond the tie zone, and compares that against a stated bar. Being
ahead is where the count landed. A clear lead is a claim that the lead would survive
another panel, and only the probability supports that.

Three figures on the report carry it, and between them they cover everything that
could be true: how likely it is that A is meaningfully ahead, how likely it is that
B is, and how likely it is that the two are practically tied.

<!-- Grounded in: `frontend/app/components/report.tsx`, `recommend` and `strongestPreference`. -->

## What the report can answer, and what each answer means

The report gives one of three answers, chosen by comparing those probabilities
against the same credibility everything else on the page is stated at.

**Panel leans clearly** — it is at least that likely that one option is meaningfully
ahead. The lead is wide enough to be worth acting on.

**Practical tie** — it is at least that likely that the two sit *inside* the tie
zone. This is the one people misread, and it is the point of the method. It is not a
failure to find a difference: it is a positive finding that whatever difference
exists is credibly too small to matter. That is something "not statistically
significant" can never say, because that phrase cannot tell apart "we found nothing"
from "there is nothing to find". Pick either option on other grounds and spend your
attention elsewhere.

**No call at this credibility** — neither of the above reached the bar. This is a
statement about the *data*, not about the options: not enough was bought to separate
the possibilities. The probabilities stay on the page, so you can read them against
your own bar instead of ours.

<!-- Grounded in: `frontend/app/components/report.tsx`, `VERDICT_COPY` and `recommend`. -->

## What a no-call still tells you

"No call" on its own is nearly unreadable — it cannot be told apart from a panel
that genuinely found equivalence. So the report also carries **the smallest gap a
panel this size could have resolved**.

That turns a shrug into a bound. "A panel this size could have detected any gap this
wide, and found none" limits how large the real difference plausibly is. If that
figure is small, the panel looked hard and saw little — a bound on the difference,
not a demonstration that the two are equivalent, which is what the practical-tie
answer is for. If it is large, the panel was simply too small to say anything, and
the honest next step is a larger one.

The figure is worked out from the panel's size and the tie zone rather than stored
anywhere, so it always describes the run in front of you.

<!-- Grounded in: `app/verdict.py`, `detectable_gap`. -->

## Why a run can stop before everyone has voted

A run may stop once the answer is already in — once more votes could not change
which of the three answers you get. It is a cost decision, made openly: votes are
paid for one at a time, and buying certainty you already have is waste.

It is not a single lucky look. The stopping bar is the same threshold the report
uses to make its recommendation, and it must be met more than once in a row before
the run stops, so a boundary crossed by chance on one batch does not end things.
When a run stops early the report says so, and says why.

<!-- Grounded in: `app/pipeline.py`, the vote loop; `docs/research/adaptive-stopping.md`. -->
