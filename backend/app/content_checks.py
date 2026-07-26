import re

# This guardrail is only for the internal prompt,
#  no user inputs are used.
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


class UnsafeInterest(ValueError):
    """An interest that reads like an injected instruction, not a hobby."""


def is_injection_like(text: str) -> bool:
    return any(pattern.search(text) for pattern in _INJECTION_PATTERNS)


def screen_interests(tags: list[str]) -> None:
    """Raise UnsafeInterest if any tag — or their concatenation — looks injected.
    This is speciic to hobby checks rg. ["ignore....", "baseball", "playing sport"]
    """
    for candidate in (*tags, " ".join(tags)):
        if is_injection_like(candidate):
            raise UnsafeInterest(
                f"interest content looks like an injected instruction: {candidate!r}"
            )
