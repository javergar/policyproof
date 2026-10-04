"""Deciding without trusting weak facts blindly (the lab's V5 re-check).

A weak fact is one a reader only scored (it couldn't quote it) below `firm_confidence`. The decision is made twice,
with and without the weak facts. If both reach the same conclusion, the weak facts didn't matter. If not, one of them
was decisive, so instead of deciding on it the customer is asked to confirm it.
"""
from typing import assert_never

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
from policyproof.core.facts import Fact, Facts, Scored, Volunteered, all_facts, facts
from policyproof.core.solver import Compiled
from policyproof.core.syntax import Ask


def _weak(f: Fact, firm_confidence: float) -> bool:
    match f.provenance:
        case Volunteered(Scored(confidence)):
            return confidence < firm_confidence
        case _:
            return False


def _conclusion(d: Decision) -> tuple[str, str]:
    """What a decision concludes, ignoring which facts it cites."""
    match d:
        case Decided(outcome, _, _):
            return "decided", outcome
        case NeedInfo(var, _, _, _):
            return "ask", var
        case Contradiction():
            return "contradiction", ""
        case Escalate():
            return "escalate", ""
        case InvalidFacts():
            return "invalid", ""
        case _:
            assert_never(d)


def _used(d: Decision) -> frozenset[str]:
    match d:
        case Decided(_, _, used) | Contradiction(_, used):
            return frozenset(f.var for f in used)
        case NeedInfo() | Escalate() | InvalidFacts():
            return frozenset()
        case _:
            assert_never(d)


def decide_robustly(c: Compiled, fs: Facts, *, unclear: frozenset[str] = frozenset(),
                    firm_confidence: float = 0.8) -> Decision:
    every = all_facts(fs)
    weak = tuple(f for f in every if _weak(f, firm_confidence))
    with_weak = decide(c, fs, unclear=unclear)
    if not weak:
        return with_weak
    strong = facts(*(f for f in every if f not in weak))
    without = decide(c, strong, unclear=unclear)
    if _conclusion(with_weak) == _conclusion(without):
        return with_weak
    askable = {v.name: v.role for v in c.policy.variables if isinstance(v.role, Ask)}
    weak_vars = {f.var for f in weak if f.var in askable}
    if not weak_vars:
        return without  # nobody can be asked about these, so decide as if they weren't said
    used = _used(with_weak)
    order = [v.name for v in c.policy.variables if v.name in weak_vars]
    var = next((n for n in order if n in used), order[0])
    role = askable[var]
    assert isinstance(role, Ask)
    return NeedInfo(var, role.question, "confirm", what_if(c, firm_facts(c, strong), var))
