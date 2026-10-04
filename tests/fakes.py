"""Fake ports for pipeline and consensus tests: each returns a scripted result and records what it was asked."""
from dataclasses import dataclass, field

from returns.result import Result

from policyproof.core.check import Problem
from policyproof.core.syntax import CheckedPolicy
from policyproof.effects.errors import LLMError
from policyproof.effects.ports import RawAnswer, RawClaim, RawFact


@dataclass
class Answers:
    result: Result[RawAnswer, LLMError]
    asked: list[str] = field(default_factory=list)

    async def read_answer(self, p: CheckedPolicy, var: str, message: str) -> Result[RawAnswer, LLMError]:
        self.asked.append(var)
        return self.result


@dataclass
class Facts:
    result: Result[tuple[RawFact, ...], LLMError]

    async def read_facts(self, p: CheckedPolicy, message: str) -> Result[tuple[RawFact, ...], LLMError]:
        return self.result


@dataclass
class Claims:
    """One scripted result per call, in order (the last repeats): the draft's claims, then the rewrite's."""
    results: list[Result[tuple[RawClaim, ...], LLMError]]
    read: list[str] = field(default_factory=list)

    async def read_claims(self, p: CheckedPolicy, reply: str) -> Result[tuple[RawClaim, ...], LLMError]:
        self.read.append(reply)
        return self.results[min(len(self.read), len(self.results)) - 1]


@dataclass
class Rewriter:
    result: Result[str, LLMError]
    problems: list[tuple[Problem, ...]] = field(default_factory=list)

    async def rewrite(self, draft: str, problems: tuple[Problem, ...], instructions: str) -> Result[str, LLMError]:
        self.problems.append(problems)
        return self.result
