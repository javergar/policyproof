"""Fake authoring ports: each returns scripted results in order (the last repeats) and records what it was asked."""
from dataclasses import dataclass, field

from returns.result import Result

from policyproof.authoring.document import Anchor, Document, Edit
from policyproof.authoring.ports import Answer, Extraction, Situation
from policyproof.core.syntax import CheckedPolicy, Rule
from policyproof.effects.errors import LLMError


def _next[T](results: list[T], calls: int) -> T:
    return results[min(calls, len(results)) - 1]


@dataclass
class Extractor:
    results: list[Result[Extraction, LLMError]]
    calls: list[tuple[CheckedPolicy | None, tuple[Anchor, ...] | None, str]] = field(default_factory=list)

    async def extract(self, doc: Document, *, vocabulary: CheckedPolicy | None = None,
                      only: tuple[Anchor, ...] | None = None, guidance: str = "") -> Result[Extraction, LLMError]:
        self.calls.append((vocabulary, only, guidance))
        return _next(self.results, len(self.calls))


@dataclass
class Drafter:
    results: list[Result[tuple[Edit, ...], LLMError]]
    failures: list[str | None] = field(default_factory=list)
    answers: list[Answer] = field(default_factory=list)
    situations: list[Situation] = field(default_factory=list)

    async def draft(self, doc: Document, situation: Situation, answer: Answer,
                    failure: str | None) -> Result[tuple[Edit, ...], LLMError]:
        self.failures.append(failure)
        self.situations.append(situation)
        self.answers.append(answer)
        return _next(self.results, len(self.failures))


@dataclass
class Phraser:
    title_result: Result[str, LLMError]
    sentence_result: Result[str, LLMError]

    async def title(self, p: CheckedPolicy, customer: tuple[str, ...]) -> Result[str, LLMError]:
        return self.title_result

    async def sentence(self, p: CheckedPolicy, rule: Rule) -> Result[str, LLMError]:
        return self.sentence_result
