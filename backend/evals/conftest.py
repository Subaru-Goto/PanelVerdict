"""DeepEval phones home with anonymous usage telemetry unless told not to; a run of
these cases reports nothing to anyone (110/#238). Set, not forced: a developer who
opted in elsewhere keeps their choice."""

import os

os.environ.setdefault("DEEPEVAL_TELEMETRY_OPT_OUT", "YES")
