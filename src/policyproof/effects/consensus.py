"""Two readers as one, combined so that a disagreement errs on the safe side.

- `AgreeingFacts` keeps only facts both readers found: fewer facts means more questions, never a wrong decision. A
  reader that can't read a variable at all (`FactsItCantRead`, as Jev and numbers) has no say on it, so the other's
  facts about it stand, as a single reader's.
- `AgreeingAnswers` accepts an answer only if both read the same value; otherwise the question is asked again.
- `UnionClaims` checks every claim either reader found: more claims can only fail more drafts.

Values are compared as policy literals, so Jev's `"true"` agrees with an LLM's `True`. A failed reader is never outvoted
by the other: if one fails, `AgreeingFacts` and `UnionClaims` return its error and `AgreeingAnswers` returns `Unclear`,
as on a disagreement; if both fail, the error that speaks more strongly against a reading is returned (`errors.worse`: a
failure to run, then a refusal, then an unsupported read; the first on a tie). The exception is an `Unsupported` reader
(one that can't read that kind of value at all, like Jev and number answers): it has no reading, so `AgreeingAnswers`
returns the other's answer, as a single reader's. Ports return only a `Result`, so a one-sided failure (other than
`Unsupported`) and a disagreement are also reported on the `policyproof.consensus` logger at WARNING.
"""
import asyncio
import json
import logging
from collections.abc import Awaitable, Sequence
from dataclasses import dataclass

from returns.result import Failure, Result, Success

from policyproof.core._result import unreachable
from policyproof.core.facts import Evidence, Quoted, Scored
from policyproof.core.syntax import CheckedPolicy, Lit, Policy
from policyproof.effects.errors import LLMError, Unsupported, describe, worse
from policyproof.effects.ports import (
    AnswerReader,
    ClaimReader,
    FactReader,
    FactsItCantRead,
    NotAnswered,
    RawAnswer,
    RawClaim,
    RawFact,
    Said,
    Unclear,
)
from policyproof.guards.values import in_text, literal_for

log = logging.getLogger("policyproof.consensus")


async def _both[T](a: Awaitable[Result[T, LLMError]], b: Awaitable[Result[T, LLMError]]
                   ) -> tuple[Result[T, LLMError], Result[T, LLMError]]:
    ra, rb = await asyncio.gather(a, b)
    match ra, rb:
        case (Failure(Unsupported()), Success(_)) | (Success(_), Failure(Unsupported())):
            pass
        case (Failure(e), Success(_)) | (Success(_), Failure(e)):
            log.warning("one reader failed, so the other's result is not used alone: %s", describe(e))
        case _:
            pass
    return ra, rb


def _key(p: Policy, f: RawFact) -> tuple[str, Lit] | None:
    lit = literal_for(p, f.var, f.value).value_or(None)
    return None if lit is None else (f.var, lit)


def _evidence(a: Evidence, b: Evidence) -> Evidence:
    match a, b:
        case Quoted(), _:
            return a
        case _, Quoted():
            return b
        case Scored(x), Scored(y):
            return Scored(min(x, y))
        case _:
            unreachable()


def agree_facts(p: Policy, a: Sequence[RawFact], b: Sequence[RawFact], *, a_cant: frozenset[str] = frozenset(),
                b_cant: frozenset[str] = frozenset()) -> tuple[RawFact, ...]:
    """The facts both readers report, with the better evidence, and the facts one reports about a variable the other
    can't read at all (`a_cant`, `b_cant`), as that reader reported them."""
    first_b: dict[tuple[str, Lit], RawFact] = {}
    for f in b:
        k = _key(p, f)
        if k is not None:
            first_b.setdefault(k, f)
    kept: dict[tuple[str, Lit], RawFact] = {}
    for f in a:
        k = _key(p, f)
        if k is None or k in kept:
            continue
        if f.var in b_cant and f.var not in a_cant:
            kept[k] = f
        elif k in first_b:
            kept[k] = RawFact(f.var, f.value, _evidence(f.evidence, first_b[k].evidence))
    for f in b:
        k = _key(p, f)
        if k is not None and f.var in a_cant and f.var not in b_cant:
            kept.setdefault(k, f)
    agreed = {var for var, _ in kept}
    for var in sorted(({f.var for f in a} & {f.var for f in b}) - agreed):
        log.warning("readers disagree on %s; dropping it", var)
    return tuple(kept.values())


def _cant_read(r: FactReader, p: CheckedPolicy) -> frozenset[str]:
    return r.cant_read(p) if isinstance(r, FactsItCantRead) else frozenset()


def agree_answers(p: Policy, var: str, message: str, a: RawAnswer, b: RawAnswer) -> RawAnswer:
    match a, b:
        case Said(x, qa), Said(y, qb):
            lx, ly = literal_for(p, var, x).value_or(None), literal_for(p, var, y).value_or(None)
            if x != y and (lx is None or lx != ly):
                return Unclear("readers disagree")
            return Said(x, qa if in_text(qa, message) or not in_text(qb, message) else qb)
        case NotAnswered(), NotAnswered():
            return a
        case Unclear(), Unclear():
            return a
        case _:
            return Unclear("readers disagree")


def union_claims(a: Sequence[RawClaim], b: Sequence[RawClaim]) -> tuple[RawClaim, ...]:
    seen: dict[tuple[str, str], RawClaim] = {}
    for c in (*a, *b):
        seen.setdefault((json.dumps(c.expr, sort_keys=True, default=str), c.quote), c)
    return tuple(seen.values())


@dataclass(frozen=True, slots=True)
class AgreeingFacts:
    a: FactReader
    b: FactReader

    async def read_facts(self, p: CheckedPolicy, message: str) -> Result[tuple[RawFact, ...], LLMError]:
        ra, rb = await _both(self.a.read_facts(p, message), self.b.read_facts(p, message))
        match ra, rb:
            case Success(xs), Success(ys):
                return Success(agree_facts(p, xs, ys, a_cant=_cant_read(self.a, p), b_cant=_cant_read(self.b, p)))
            case Failure(ea), Failure(eb):
                return Failure(worse(ea, eb))
            case Failure(_), _:
                return ra
            case _:
                return rb

    def cant_read(self, p: CheckedPolicy) -> frozenset[str]:
        """What neither reader can read, so a combined reader nested in another keeps Jev's exemption."""
        return _cant_read(self.a, p) & _cant_read(self.b, p)


@dataclass(frozen=True, slots=True)
class AgreeingAnswers:
    a: AnswerReader
    b: AnswerReader

    async def read_answer(self, p: CheckedPolicy, var: str, message: str) -> Result[RawAnswer, LLMError]:
        ra, rb = await _both(self.a.read_answer(p, var, message), self.b.read_answer(p, var, message))
        match ra, rb:
            case Success(x), Success(y):
                return Success(agree_answers(p, var, message, x, y))
            case Failure(Unsupported()), Success(_):
                return rb
            case Success(_), Failure(Unsupported()):
                return ra
            case (Failure(e), Success(_)) | (Success(_), Failure(e)):
                return Success(Unclear(f"a reader failed: {describe(e)}"))
            case Failure(ea), Failure(eb):
                return Failure(worse(ea, eb))  # an unsupported reader's error never hides the other's real one
            case _:
                unreachable()


@dataclass(frozen=True, slots=True)
class UnionClaims:
    a: ClaimReader
    b: ClaimReader

    async def read_claims(self, p: CheckedPolicy, reply: str) -> Result[tuple[RawClaim, ...], LLMError]:
        ra, rb = await _both(self.a.read_claims(p, reply), self.b.read_claims(p, reply))
        match ra, rb:
            case Success(xs), Success(ys):
                return Success(union_claims(xs, ys))
            case Failure(ea), Failure(eb):
                return Failure(worse(ea, eb))
            case Failure(_), _:
                return ra
            case _:
                return rb
