"""The chat pre-flight (120/#279): one classifier call on the reader's message
before the analyst sees it.

Blocks the bare "ignore your instructions" shape deterministically; an
injection behind an ordinary question mostly passes, and topic is not its
job (`docs/research/moderation-check.md`). Fails open like the headline
screener: a classifier outage is never a product outage. Logs a score and a
verdict, never the text.
"""

from __future__ import annotations

import logging
from collections.abc import Collection
from dataclasses import dataclass, field
from typing import Protocol

import httpx

# One reading of "off" for both controls (072/#163): these statuses say the key
# or model is wrong for this account; anything else is an outage.
from app.screening import _CONFIGURATION_STATUSES, ProbeOutcome

logger = logging.getLogger(__name__)

# The only category read. Everything else the classifier returns is ignored:
# Financial fired on a savings-account question in the measurement, and a
# general category would block a reader's own subject.
DECISION_CATEGORY = "jailbreaking"
# The slowest single request measured was 254 ms, a message at the chat cap
# (moderation-check.md); 2 s is that rounded up to a whole second with room
# for a tail the six timed requests could not show. Still waiting then, the
# pre-flight fails open.
GUARD_TIMEOUT_SECONDS = 2.0
MODERATE_PATH = "/moderations"
# Chat case r01 of the measured corpus: scored 0.0004 (moderation-check.md).
_PROBE_TEXT = "What does the tie zone mean in my report?"


@dataclass(frozen=True)
class Classification:
    """What the pre-flight reads from one reply: the decision score, and the
    categories the classifier itself flagged (its own per-category threshold —
    122/#288: the corpus has no positives for the content categories, so the
    classifier's flag is the only sourced cut)."""

    jailbreaking: float
    flagged: frozenset[str] = field(default_factory=frozenset)


class ChatGuard(Protocol):
    model_name: str

    async def classify(self, text: str) -> Classification: ...

    async def aclose(self) -> None: ...


class MistralChatGuard:
    """`POST /v1/moderations`, shape from Mistral's OpenAPI file (read 2026-09-03)."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.model_name = model
        self._headers = {"Authorization": f"Bearer {api_key}"}
        self._base_url = base_url
        self._client = client or httpx.AsyncClient(timeout=GUARD_TIMEOUT_SECONDS)

    async def classify(self, text: str) -> Classification:
        response = await self._client.post(
            f"{self._base_url}{MODERATE_PATH}",
            json={"model": self.model_name, "input": [text]},
            headers=self._headers,
            timeout=GUARD_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        [result] = response.json()["results"]
        scores = result["category_scores"]
        if DECISION_CATEGORY not in scores:
            raise NoDecisionScore(f"no {DECISION_CATEGORY} score in the reply")
        flagged = frozenset(c for c, hit in result["categories"].items() if hit)
        return Classification(float(scores[DECISION_CATEGORY]), flagged)

    async def aclose(self) -> None:
        await self._client.aclose()


class NoDecisionScore(RuntimeError):
    """The model answered, but not with the score this control reads — the
    control is off, not degraded."""


class BlockedMessage(Exception):
    """The reader's message scored as an instruction aimed at the model.

    An exception, like `UnsafeInput`: refusing is the default path. The
    sentence is this codebase's own; nothing from the classifier travels.
    """

    def __init__(self) -> None:
        super().__init__(
            "This message reads as an instruction aimed at the analyst rather than"
            " a question about your report, so it was not sent. Ask about this test's"
            " results, what they mean, or how headlines tend to perform."
        )


class ContentRefused(Exception):
    """The classifier flagged the message in a content category the product
    refuses (122/#288). One sentence for every category, so the door is not a
    labelled oracle; the category goes to the log, never to the reader."""

    def __init__(self) -> None:
        super().__init__(
            "That is outside what the analyst discusses here. Ask about this test's"
            " results, what they mean, or how headlines tend to perform."
        )


async def guard_chat_message(
    guard: ChatGuard | None,
    text: str,
    *,
    threshold: float,
    content: Collection[str],
) -> None:
    """Refuse a message whose decision score reaches the threshold, or that the
    classifier flags in a refused content category; let everything else through,
    including a message the classifier could not score."""
    if guard is None:
        return
    try:
        verdict = await guard.classify(text)
    except Exception as error:
        # Fail open, type name only: the error may carry the request body.
        # ERROR when the key or model is wrong for this account, WARNING for
        # an outage — the screener's distinction: a revoked key is not a blip.
        logger.log(
            logging.ERROR if _classify(error) == "off" else logging.WARNING,
            "chat pre-flight did not run (%s): model=%s",
            type(error).__name__,
            guard.model_name,
        )
        return
    category: str | None = None
    if verdict.jailbreaking >= threshold:
        category = DECISION_CATEGORY
    else:
        # Deterministic order, so the logged category does not depend on the
        # reply's key order when two are flagged at once.
        category = next((c for c in content if c in verdict.flagged), None)
    logger.log(
        logging.WARNING if category else logging.INFO,
        "chat pre-flight",
        extra={
            "chat_guard": "refused" if category else "pass",
            "chat_guard_score": verdict.jailbreaking,
            "chat_guard_category": category,
        },
    )
    if category == DECISION_CATEGORY:
        raise BlockedMessage()
    if category is not None:
        raise ContentRefused()


def _classify(error: Exception) -> ProbeOutcome:
    if isinstance(error, NoDecisionScore):
        return "off"
    if isinstance(error, httpx.HTTPStatusError):
        if error.response.status_code in _CONFIGURATION_STATUSES:
            return "off"
    return "outage"


async def probe_chat_guard(guard: ChatGuard) -> ProbeOutcome:
    """One real call at boot, so a wrong key is announced once rather than
    failing open silently on every request."""
    try:
        await guard.classify(_PROBE_TEXT)
    except Exception as error:
        return _classify(error)
    return "runs"
