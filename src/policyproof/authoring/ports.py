"""What the authoring layer needs from models: an extractor, a drafter and a phraser. Each port is one async method
returning a `Result`; no exception crosses a port. Only `authoring.llm` implements them with a real model."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from returns.result import Result

from policyproof.authoring.document import Anchor, Document, Edit
from policyproof.authoring.extraction import Extraction, Link
from policyproof.core.syntax import CheckedPolicy, Rule
from policyproof.effects.errors import LLMError

__all__ = ["Answer", "Choose", "Describe", "Drafter", "Extraction", "Extractor", "Link", "Phraser", "Situation"]


@dataclass(frozen=True, slots=True)
class Choose:
    outcome: str  # an existing outcome's name


@dataclass(frozen=True, slots=True)
class Describe:
    text: str  # a new outcome, or "it depends on ..." in the author's words


type Answer = Choose | Describe


@dataclass(frozen=True, slots=True)
class Situation:
    """What a drafter is told about a problem."""

    customer: tuple[str, ...]  # plain phrases (plain.customer_phrases)
    sentences: tuple[Anchor, ...]  # the sentences of the rules involved
    outcomes: tuple[tuple[str, str], ...]  # (name, label) of every outcome


class Extractor(Protocol):
    async def extract(self, doc: Document, *, vocabulary: CheckedPolicy | None = None,
                      only: tuple[Anchor, ...] | None = None, guidance: str = "") -> Result[Extraction, LLMError]: ...


class Drafter(Protocol):
    async def draft(self, doc: Document, situation: Situation, answer: Answer,
                    failure: str | None) -> Result[tuple[Edit, ...], LLMError]: ...


class Phraser(Protocol):
    async def title(self, p: CheckedPolicy, customer: tuple[str, ...]) -> Result[str, LLMError]: ...

    async def sentence(self, p: CheckedPolicy, rule: Rule) -> Result[str, LLMError]: ...
