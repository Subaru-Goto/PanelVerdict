"""Detect text that reads like an injected instruction rather than content.

Kept after 006j removed its only caller. No persona field is free text any more,
so the pool can no longer be poisoned through generation — but these patterns are
what 013 needs at the runtime boundary, where the headline variants and the target
description actually arrive from a user. Screening belongs there, not here.
"""

import re

_INJECTION_PATTERNS = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\bignore\b.*\b(instruction|previous|prior|above|all)\b",
        r"\bdisregard\b.*\b(instruction|previous|prior|above|all)\b",
        r"\bforget\b.*\b(instruction|everything|above|previous)\b",
        r"\byou are (now )?an?\b",
        r"\bact as\b",
        r"\bpretend (to|that|you)\b",
        r"\bsystem prompt\b",
        r"\brespond with\b",
        r"\boverride\b",
        r"\b(vote|choose|pick|select)\b.*\boption\b",
        r"\boption[_ ]?[12]\b",
    )
]


def is_injection_like(text: str) -> bool:
    return any(pattern.search(text) for pattern in _INJECTION_PATTERNS)
