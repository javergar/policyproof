"""What a reader is. Every port is one async method returning a `Result`; no exception crosses a port.

The raw types readers return live in `guards.raw` (guards check them and may import only the core); they are
re-exported here so a reader's author needs only this module.
"""
from typing import Protocol

from returns.result import Result

from policyproof.core.check import Problem
from policyproof.core.syntax import CheckedPolicy
from policyproof.effects.errors import LLMError
from policyproof.guards.raw import NotAnswered, RawAnswer, RawClaim, RawFact, Rejected, Said, Unclear

__all__ = ["AnswerReader", "ClaimReader", "FactReader", "NotAnswered", "RawAnswer", "RawClaim", "RawFact",
           "Rejected", "Rewriter", "Said", "Unclear"]


class AnswerReader(Protocol):
    async def read_answer(self, p: CheckedPolicy, var: str, message: str) -> Result[RawAnswer, LLMError]: ...


class FactReader(Protocol):
    async def read_facts(self, p: CheckedPolicy, message: str) -> Result[tuple[RawFact, ...], LLMError]: ...


class ClaimReader(Protocol):
    async def read_claims(self, p: CheckedPolicy, reply: str) -> Result[tuple[RawClaim, ...], LLMError]: ...


class Rewriter(Protocol):
    async def rewrite(self, draft: str, problems: tuple[Problem, ...], instructions: str) -> Result[str, LLMError]: ...
