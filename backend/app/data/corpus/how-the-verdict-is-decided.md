# How the verdict is decided

This explains what the report's answer means and how it was reached. Every number
you need is on the report itself — this page is about what those numbers are
*for*.

## What the panel is actually measuring

Each panelist is shown both headlines and says which they prefer. Half of them see
your first headline first, so a habit of picking whatever comes first cannot
disguise itself as a preference.

What comes out of that is a share: out of everyone who voted, how many preferred
B. That share is the whole measurement. It is not a score, a rating, or a
prediction of clicks — it is the fraction of a synthetic panel that leaned one way
when asked to choose.

## Why the answer is a range and not one number

The share you would get is not the share you would get again. Ask a different
panel of the same size and you would get a slightly different number, the way two
polls of the same electorate disagree.

So the report gives a **credible interval**: a range, with a stated probability
that the true preference of a panel like this one falls inside it. Read it exactly
that way — "there is that much probability the real share is in here". That is a
plainer thing than the confidence interval you may have met in a statistics class,
which is a statement about the procedure rather than about this particular answer.

A wide interval means the panel did not buy much certainty. A narrow one means it
did. The width comes from how many people voted, and it narrows slowly: buying
twice the confidence costs far more than twice the panel.

**Grounded in:** `app/verdict.py`, `posterior` — a Beta-Binomial posterior over
the share preferring B, with a flat prior.

## The tie zone, and why there is one

Some differences are real and still not worth acting on. If one headline is
very slightly ahead, forever, that is a fact about the world and a waste of your
afternoon.

So the report carries a band around dead even — a zone of differences small enough
that we are willing to call them equivalent in practice. Its width is on the
report, and it was chosen deliberately rather than derived: it encodes what size
of difference is worth acting on, which is a judgement about your decision, not
something the arithmetic can hand you.

Two things pinned the width. Narrower, and the interval could never fit inside it
at any panel size anyone would pay for, so "these are equivalent" would have been
an answer the product could never give. And the band sits inside the panel's own
run-to-run wobble — the amount the same panel's answer moves when nothing about
the headlines has changed. Calling a difference that small a tie is honesty rather
than laxity.

**Grounded in:** `app/verdict.py`, `_ROPE` and `rope_verdict`;
`docs/research/adaptive-stopping.md`.

## Why "ahead" is not the same as "decisive"

This is the question the report is most often asked, and the answer is the whole
method in one line: **the entire interval has to clear the tie zone, not merely
lean past it.**

A headline can be ahead in the raw count while the interval around that lead still
overlaps the tie zone. That overlap is the report saying: given how few people
voted, a world where these two headlines are equivalent has not been ruled out.
Being ahead is where the count landed. Being decisive is a claim that the lead
would survive another panel — and only a range that sits wholly outside the tie
zone supports it.

The band is closed at its edges. An interval that merely touches the edge still
has some probability sitting on differences the band calls negligible, so it
cannot claim decisive either.

**Grounded in:** `app/verdict.py`, `rope_verdict`.

## The three answers, and why a tie is a finding

**Decisive** — the interval sits entirely outside the tie zone. One headline is
ahead by an amount worth acting on.

**Undecided** — the interval straddles the boundary. This is a statement about the
*data*, not about the headlines: not enough was bought to separate the two
possibilities.

**Practical tie** — the interval sits entirely *inside* the tie zone. This is the
one people misread, and it is the point of the method. It is not a failure to find
a difference. It is a positive finding: whatever difference exists is credibly too
small to matter. That is a real answer, and it is one that "not statistically
significant" can never give you — that phrase cannot tell apart "we found nothing"
from "there is nothing to find".

If you get a practical tie, you have learned something worth knowing: pick either
headline on other grounds and spend your attention elsewhere.

**Grounded in:** `app/verdict.py`, `rope_verdict` — *"the third is the point of the
method"*.

## What an undecided result still tells you

`Undecided` on its own is nearly unreadable — it cannot be told apart from a panel
that genuinely found equivalence. So the report also carries **the smallest gap a
panel this size could have called decisive**.

That turns a shrug into a finding. "A panel this size could have detected any gap
this wide, and found none" bounds how large the real difference plausibly is. If
that figure is small, an undecided result is close to a tie. If it is large, the
panel was simply too small to say anything, and the honest next step is a larger
one.

The figure is worked out from the panel's size and the tie zone rather than stored
anywhere, so it always describes the run in front of you.

**Grounded in:** `app/verdict.py`, `detectable_gap`.

## Why a run can stop before everyone has voted

A run may stop once the answer is already in — once more votes could not change
which of the three answers you get. It is a cost decision, made openly: votes are
paid for one at a time, and buying certainty you already have is waste.

It is not a single lucky look. The stopping bar is the same threshold the report
uses to make its recommendation, and it must be met more than once in a row before
the run stops, so a boundary crossed by chance on one batch does not end things.
When a run stops early the report says so, and says why.

**Grounded in:** `app/pipeline.py`, the vote loop;
`docs/research/adaptive-stopping.md`.
