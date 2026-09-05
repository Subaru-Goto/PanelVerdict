"""The free half of evaluation (110/#238): deterministic DeepEval cases over the
committed demo captures, run on every push at no cost.

Outside `tests/` on purpose. DeepEval cannot live in the project's lock — its caps
would downgrade the production image (see requirements.txt) — so these run under
an overlay the main suite never loads:

    uv run --with-requirements evals/requirements.txt python -m pytest evals

CI runs exactly that as its own step. No client exists here by construction; a
metric that needs a model call cannot be written in this directory without one.
"""
