"""Grading one run of a case: correct, conservative (it asked again, escalated, or fell back) or wrong (it decided
the wrong thing, misread a fact, or let a bad draft through). Pure: the runner reduces what the pipelines returned to
the observations below, so grading needs nothing but the core.
"""
from collections.abc import Iterable
from dataclasses import dataclass
from typing import assert_never

from policyproof.core.decide import Contradiction, Decided, Decision, Escalate, InvalidFacts, NeedInfo
from policyproof.core.facts import Facts
from policyproof.core.render import pretty
from policyproof.eval.cases import AskExpected, EscalateExpected, OutcomeExpected, ReplyCase, TurnCase


@dataclass(frozen=True, slots=True)
class Correct:
    pass


@dataclass(frozen=True, slots=True)
class Conservative:
    reason: str


@dataclass(frozen=True, slots=True)
class Wrong:
    reason: str


type Grade = Correct | Conservative | Wrong


@dataclass(frozen=True, slots=True)
class TurnSeen:
    """What a turn produced: its decision and every fact it ended with."""
    decision: Decision
    facts: Facts


@dataclass(frozen=True, slots=True)
class ReaderFailed:
    """The turn failed with a reader error (`LLMError`)."""
    reason: str


@dataclass(frozen=True, slots=True)
class Crashed:
    """A reader raised an exception: a bug that would reach a customer."""
    reason: str


@dataclass(frozen=True, slots=True)
class ReplySeen:
    as_written: bool  # the draft was sent unchanged


type TurnOutcome = TurnSeen | ReaderFailed | Crashed
type ReplyOutcome = ReplySeen | Crashed


def rank(g: Grade) -> int:
    match g:
        case Correct():
            return 0
        case Conservative():
            return 1
        case Wrong():
            return 2
        case _:
            assert_never(g)


def worst(grades: Iterable[Grade]) -> Grade:
    """The worst grade (the first of equals), or `Correct()` for none."""
    found: Grade = Correct()
    for g in grades:
        if rank(g) > rank(found):
            found = g
    return found


def _instead(d: Decision) -> str:
    match d:
        case NeedInfo(var, _, _, _):
            return f"asked about {var}"
        case Escalate(reason):
            return f"escalated ({reason})"
        case Contradiction():
            return "found a contradiction"
        case Decided(outcome, _, _):
            return f"decided {outcome}"
        case InvalidFacts(errors):
            return f"invalid facts: {'; '.join(errors)}"
        case _:
            assert_never(d)


def _decision(case: TurnCase, d: Decision) -> Grade:
    if isinstance(d, InvalidFacts):
        return Wrong(f"invalid facts reached the decision: {'; '.join(d.errors)}")
    expect = case.expect
    match expect:
        case OutcomeExpected(name):
            match d:
                case Decided(outcome, _, _) if outcome == name:
                    return Correct()
                case Decided(outcome, _, _):
                    return Wrong(f"decided {outcome}, expected {name}")
                case _:
                    return Conservative(f"{_instead(d)} instead of deciding {name}")
        case AskExpected(var):
            match d:
                case NeedInfo(asked, _, _, _) if asked == var:
                    return Correct()
                case NeedInfo(asked, _, _, _):
                    return Conservative(f"asked about {asked}, expected {var}")
                case Decided(outcome, _, _):
                    return Wrong(f"decided {outcome}, expected a question about {var}")
                case _:
                    return Conservative(f"{_instead(d)} instead of asking about {var}")
        case EscalateExpected():
            match d:
                case Escalate() | Contradiction():
                    return Correct()
                case Decided(outcome, _, _):
                    return Wrong(f"decided {outcome}, expected an escalation")
                case _:
                    return Conservative(f"{_instead(d)} instead of escalating")
        case _:
            assert_never(expect)


def _facts(case: TurnCase, fs: Facts) -> Grade:
    grades: list[Grade] = []
    for var, want in case.expect_facts:
        read = {f.value for f in fs.get(var, frozenset())}
        if not read:
            grades.append(Conservative(f"{var} was not read"))
        elif read != {want}:
            got = ", ".join(sorted(pretty(v) for v in read - {want}))
            grades.append(Wrong(f"misread {var}: read {got}, expected {pretty(want)}"))
    return worst(grades)


def grade_turn(case: TurnCase, seen: TurnOutcome) -> Grade:
    match seen:
        case TurnSeen(decision, fs):
            return worst([_facts(case, fs), _decision(case, decision)])
        case ReaderFailed(reason):
            return Conservative(f"reader error: {reason}")
        case Crashed(reason):
            return Wrong(f"crashed: {reason}")
        case _:
            assert_never(seen)


def grade_reply(case: ReplyCase, seen: ReplyOutcome) -> Grade:
    match seen:
        case Crashed(reason):
            return Wrong(f"crashed: {reason}")
        case ReplySeen(as_written):
            if case.expect == "caught":
                return Wrong("the draft was sent as written, expected it to be caught") if as_written else Correct()
            return Correct() if as_written else Conservative("a good draft was rewritten or replaced")
        case _:
            assert_never(seen)
