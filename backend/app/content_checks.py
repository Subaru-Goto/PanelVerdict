"""Detect text that reads like an injected instruction rather than content.

Has no caller: the persona pool it used to screen holds no free text. Kept for
013, which screens the headline variants and target description a user actually
sends. Delete it if 013 lands a different approach.
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
