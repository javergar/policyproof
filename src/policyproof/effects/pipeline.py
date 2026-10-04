"""The two turn pipelines.

`read_turn` reads a customer message into facts and a decision. `guard_reply` checks a drafted reply before it is
sent, rewrites it once if it fails, and otherwise sends a deterministic fallback, so unchecked text never reaches the
customer. Both fail closed: an error means asking again or the fallback, never a decision or a claim on less evidence.
"""
import asyncio
import dataclasses
from collections.abc import Callable
from dataclasses import dataclass
from typing import assert_never

from returns.result import Failure, Result, Success

from policyproof.core._result import unreachable
from policyproof.core.check import DEFAULT_RULES, CheckResult, Problem, ReplyRule, check_reply
from policyproof.core.decide import Contradiction, Decided, Decision, Escalate, InvalidFacts, NeedInfo
from policyproof.core.facts import Facts, merge
from policyproof.core.solver import Compiled
from policyproof.effects.errors import LLMError, describe
from policyproof.effects.ports import AnswerReader, ClaimReader, FactReader, RawAnswer, Rejected, Rewriter
from policyproof.guards import answer, claims, facts
from policyproof.guards.answer import Answer, Reading
from policyproof.guards.raw import NotAnswered, Unclear
from policyproof.guards.robust import decide_robustly


@dataclass(frozen=True, slots=True)
class Conversation:
    facts: Facts  # including the system facts the caller loaded
    pending: NeedInfo | None  # the question asked last turn
    unclear: frozenset[str]  # variables whose last answer couldn't be read


@dataclass(frozen=True, slots=True)
class Readers:
    answers: AnswerReader
    facts: FactReader


@dataclass(frozen=True, slots=True)
class Turn:
    state: Conversation  # the state for the next turn: `pending` is the decision if it asks a question
    decision: Decision
    answer: Reading | None  # None when no question was pending
    rejected: tuple[Rejected, ...]
    degraded: tuple[LLMError, ...]  # errors the turn went on without


async def _no_answer() -> Result[RawAnswer | None, LLMError]:
    return Success(None)


async def read_turn(c: Compiled, state: Conversation, message: str, r: Readers, *,
                    min_confidence: float = 0.5, firm_confidence: float = 0.8) -> Result[Turn, LLMError]:
    p = c.policy
    asking = r.answers.read_answer(p, state.pending.var, message) if state.pending else _no_answer()
    raw_answer, raw_facts = await asyncio.gather(asking, r.facts.read_facts(p, message))
    match raw_answer:
        case Failure(e):
            return Failure(e)
        case Success(raw):
            pass
        case _:
            unreachable()
    known, unclear = state.facts, state.unclear
    reading: Reading | None = None
    if state.pending is not None and raw is not None:
        var = state.pending.var
        reading = answer.check(p, var, message, raw)
        match reading:
            case Answer(fact):
                known, unclear = merge(known, {var: frozenset({fact})}), unclear - {var}
            case Unclear():
                unclear = unclear | {var}
            case NotAnswered():
                pass
            case _:
                assert_never(reading)
    rejected: tuple[Rejected, ...] = ()
    degraded: tuple[LLMError, ...] = ()
    match raw_facts:
        case Success(found):
            said, rejected = facts.check(p, message, found, min_confidence=min_confidence)
            known = merge(known, said)
        case Failure(e):
            degraded = (e,)
        case _:
            unreachable()
    decision = decide_robustly(c, known, unclear=unclear, firm_confidence=firm_confidence)
    pending = decision if isinstance(decision, NeedInfo) else None
    return Success(Turn(Conversation(known, pending, unclear), decision, reading, rejected, degraded))


# ---- replies


def template(d: Decision) -> str:
    """The fallback reply: plain, deterministic, and only what the decision itself says."""
    match d:
        case Decided(outcome, _, _):
            return f"Under the policy, the outcome is {outcome.replace('_', ' ')}."
        case NeedInfo(_, question, _, _):
            return question
        case Contradiction():
            return "Some of the information conflicts; a person will review this."
        case Escalate() | InvalidFacts():
            return "A person will review this."
        case _:
            assert_never(d)


@dataclass(frozen=True, slots=True)
class Guarded:
    text: str
    attempts: int  # drafts checked: 1 or 2
    result: CheckResult | None  # the last check that ran; None if none could
    fell_back: bool
    reason: str | None  # why it fell back


async def _check(c: Compiled, fs: Facts, d: Decision, reply: str, reader: ClaimReader,
                 rules: tuple[ReplyRule, ...]) -> Result[CheckResult, LLMError]:
    """The core's check, plus one problem per claim the guard rejected: a claim that can't be checked fails it."""
    match await reader.read_claims(c.policy, reply):
        case Success(raws):
            kept, rejected = claims.check(c.policy, reply, raws)
            result = check_reply(c, d, fs, reply, kept, rules)
            unreadable = tuple(Problem("claims_readable", f'"{r.item}" can\'t be checked: {r.reason}')
                               for r in rejected)
            if not unreadable:
                return Success(result)
            return Success(dataclasses.replace(result, passed=False, problems=result.problems + unreadable))
        case Failure(e):
            return Failure(e)
        case _:
            unreachable()


async def guard_reply(c: Compiled, fs: Facts, decision: Decision, draft: str, reader: ClaimReader,
                      rewriter: Rewriter, *, rules: tuple[ReplyRule, ...] = DEFAULT_RULES, instructions: str = "",
                      fallback: Callable[[Decision], str] = template) -> Guarded:
    def fall_back(attempts: int, result: CheckResult | None, reason: str) -> Guarded:
        return Guarded(fallback(decision), attempts, result, True, reason)

    match await _check(c, fs, decision, draft, reader, rules):
        case Failure(e):
            return fall_back(1, None, describe(e))
        case Success(first):
            pass
        case _:
            unreachable()
    if first.passed:
        return Guarded(draft, 1, first, False, None)
    match await rewriter.rewrite(draft, first.problems, instructions):
        case Failure(e):
            return fall_back(1, first, describe(e))
        case Success(rewrite):
            pass
        case _:
            unreachable()
    match await _check(c, fs, decision, rewrite, reader, rules):
        case Failure(e):
            return fall_back(2, first, describe(e))
        case Success(second) if second.passed:
            return Guarded(rewrite, 2, second, False, None)
        case Success(second):
            return fall_back(2, second, "the reply failed the check twice")
        case _:
            unreachable()
