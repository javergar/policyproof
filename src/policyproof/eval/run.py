"""Running cases through the turn pipelines, for each reader configuration, and grading every run.

A turn case starts from its given facts and pending question and runs `read_turn` on its message. A reply case decides
from its facts and runs `guard_reply` on its draft. Each run is reduced to what grading needs (`eval.grade`) plus a
few lines of trace for the report. An exception from a reader is a bug: the run is graded wrong and the rest go on.
"""
import asyncio
import time
from collections.abc import Sequence
from dataclasses import dataclass
from typing import assert_never

from returns.result import Failure, Success

from policyproof.core._result import unreachable
from policyproof.core.check import normalize
from policyproof.core.decide import (
    Contradiction,
    Decided,
    Decision,
    Escalate,
    InvalidFacts,
    NeedInfo,
    decide,
    firm_facts,
    what_if,
)
from policyproof.core.facts import Answered, Fact, FromSystem, Quoted, Scored, Volunteered, all_facts
from policyproof.core.render import pretty
from policyproof.core.solver import Compiled, compile
from policyproof.core.syntax import Ask
from policyproof.effects.errors import describe
from policyproof.effects.pipeline import Conversation, Guarded, Readers, Turn, guard_reply, read_turn
from policyproof.effects.ports import AnswerReader, ClaimReader, FactReader, NotAnswered, Rewriter, Unclear
from policyproof.eval.cases import Case, CaseFile, ReplyCase, TurnCase
from policyproof.eval.grade import Crashed, Grade, ReaderFailed, ReplySeen, TurnSeen, grade_reply, grade_turn
from policyproof.eval.report import Report, RunResult, case_result, configuration_result
from policyproof.guards.answer import Answer, Reading


@dataclass(frozen=True, slots=True)
class Configuration:
    """One way of reading text: built by `eval.config` from readers.yaml, or by hand."""
    name: str
    answers: AnswerReader
    facts: FactReader
    claims: ClaimReader
    rewriter: Rewriter
    min_confidence: float = 0.5
    firm_confidence: float = 0.8


def _decision_line(d: Decision) -> str:
    match d:
        case Decided(outcome, rules, _):
            return f"decision: decided {outcome} (rules {', '.join(rules)})"
        case NeedInfo(var, _, reason, _):
            return f"decision: asks about {var} ({reason})"
        case Escalate(reason):
            return f"decision: escalates ({reason})"
        case Contradiction(rules, _):
            return f"decision: contradiction (rules {', '.join(rules)})"
        case InvalidFacts(errors):
            return f"decision: invalid facts ({'; '.join(errors)})"
        case _:
            assert_never(d)


def _source(f: Fact) -> str:
    match f.provenance:
        case FromSystem(source):
            return f"from {source}"
        case Answered(_, quote):
            return f'answered: "{quote}"'
        case Volunteered(Quoted(text)):
            return f'said: "{text}"'
        case Volunteered(Scored(confidence)):
            return f"scored {confidence:.2f}"
        case _:
            unreachable()


def _answer_line(r: Reading) -> str:
    match r:
        case Answer(fact):
            return f"answer: {fact.var} = {pretty(fact.value)}"
        case Unclear(reason):
            return f"answer unclear: {reason}"
        case NotAnswered():
            return "not answered"
        case _:
            assert_never(r)


def _turn_trace(case: TurnCase, t: Turn) -> tuple[str, ...]:
    given = set(all_facts(case.facts))
    lines = [_decision_line(t.decision)]
    lines += [f"read {f.var} = {pretty(f.value)} ({_source(f)})" for f in all_facts(t.state.facts) if f not in given]
    lines += [_answer_line(t.answer)] if t.answer is not None else []
    lines += [f"rejected {r.item}: {r.reason}" for r in t.rejected]
    lines += [f"degraded: {describe(e)}" for e in t.degraded]
    return tuple(lines)


def _reply_trace(g: Guarded) -> tuple[str, ...]:
    if g.fell_back:
        head = f"fell back ({g.reason}): {g.text}"
    elif g.attempts == 1:
        head = f"sent as written: {g.text}"
    else:
        head = f"sent after {g.attempts} attempts: {g.text}"
    lines = [head]
    if g.result is not None:
        lines += [f'claim "{r.claim.quote}": {pretty(r.claim.expr)} is {r.status.replace("_", " ")}'
                  for r in g.result.claims]
        lines += [f"problem ({p.rule}): {p.message}" for p in g.result.problems]
    return tuple(lines)


def _pending(c: Compiled, case: TurnCase) -> NeedInfo | None:
    if case.asked is None:
        return None
    role = next(v.role for v in c.policy.variables if v.name == case.asked)
    assert isinstance(role, Ask)
    return NeedInfo(case.asked, role.question, "missing", what_if(c, firm_facts(c, case.facts), case.asked))


async def _turn(c: Compiled, cfg: Configuration, case: TurnCase) -> tuple[Grade, tuple[str, ...]]:
    state = Conversation(case.facts, _pending(c, case), frozenset())
    try:
        result = await read_turn(c, state, case.message, Readers(cfg.answers, cfg.facts),
                                 min_confidence=cfg.min_confidence, firm_confidence=cfg.firm_confidence)
    except Exception as e:
        crash = f"{type(e).__name__}: {e}"
        return grade_turn(case, Crashed(crash)), (f"crashed: {crash}",)
    match result:
        case Success(t):
            return grade_turn(case, TurnSeen(t.decision, t.state.facts)), _turn_trace(case, t)
        case Failure(e):
            return grade_turn(case, ReaderFailed(describe(e))), (f"reader error: {describe(e)}",)
        case _:
            unreachable()


async def _reply(c: Compiled, cfg: Configuration, case: ReplyCase) -> tuple[Grade, tuple[str, ...]]:
    d = decide(c, case.facts)
    try:
        g = await guard_reply(c, case.facts, d, case.draft, cfg.claims, cfg.rewriter)
    except Exception as e:
        crash = f"{type(e).__name__}: {e}"
        return grade_reply(case, Crashed(crash)), (f"crashed: {crash}",)
    # "As written" is about the text sent, not the number of attempts: a rewrite that returns the draft unchanged
    # and passes a second (mis)read still sends the draft.
    seen = ReplySeen(as_written=not g.fell_back and normalize(g.text) == normalize(case.draft))
    return grade_reply(case, seen), (_decision_line(d), *_reply_trace(g))


async def _job(c: Compiled, cfg: Configuration, case: Case, run: int, limit: asyncio.Semaphore) -> RunResult:
    async with limit:
        start = time.perf_counter()
        match case:
            case TurnCase():
                grade, trace = await _turn(c, cfg, case)
            case ReplyCase():
                grade, trace = await _reply(c, cfg, case)
            case _:
                assert_never(case)
        return RunResult(run, grade, round(time.perf_counter() - start, 2), trace)


async def evaluate(f: CaseFile, configurations: Sequence[Configuration], *, runs: int = 3,
                   concurrency: int = 4) -> Report:
    if runs < 1 or concurrency < 1:
        raise ValueError(f"runs and concurrency must be at least 1, got runs={runs}, concurrency={concurrency}")
    if not f.cases:
        raise ValueError("no cases to evaluate: an empty case file would pass the gate without testing anything")
    c = compile(f.policy)
    limit = asyncio.Semaphore(concurrency)
    results = []
    for cfg in configurations:
        per_case = await asyncio.gather(*(
            asyncio.gather(*(_job(c, cfg, case, n, limit) for n in range(1, runs + 1))) for case in f.cases))
        results.append(configuration_result(cfg.name, [
            case_result(case.id, case.held_out, tuple(rs)) for case, rs in zip(f.cases, per_case, strict=True)]))
    return Report(f.policy.name, runs, tuple(results))
