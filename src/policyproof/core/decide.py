"""Deciding: the first outcome the facts prove, or the one question that settles it.

1. The rules and all facts must be consistent, or the result is a `Contradiction` naming the rules and facts.
2. The first outcome (in policy order) proven from the firm facts is `Decided`. Firm facts are the ones that come from
   a system or answer a question, plus volunteered facts about variables that don't need confirmation.
3. If an outcome is proven only with a volunteered fact, that fact is confirmed first: `NeedInfo(reason="confirm")`.
4. Otherwise the policy asks about the askable variable whose answers decide the most outcomes (the what-if table),
   ties broken by policy order. With nothing left to ask: `Escalate`.
"""
from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Literal, assert_never

from policyproof.core.facts import Answered, Fact, Facts, Volunteered, all_facts
from policyproof.core.prove import Proven, classify
from policyproof.core.semantics import free_vars, rule_expr
from policyproof.core.solver import Compiled, FactLabel, Label, RuleLabel, Sat, Unknown, Unsat, check, fact
from policyproof.core.syntax import (
    And,
    Ask,
    BoolLit,
    BoolSort,
    Cmp,
    EnumLit,
    EnumSort,
    Expr,
    Lit,
    Outcome,
    Var,
    Variable,
)

type Reason = Literal["missing", "confirm", "unclear"]


@dataclass(frozen=True, slots=True)
class Decided:
    outcome: str
    rules: tuple[str, ...]
    facts_used: tuple[Fact, ...]


@dataclass(frozen=True, slots=True)
class NeedInfo:
    var: str
    question: str
    reason: Reason
    what_if: tuple[tuple[Lit, str | None], ...]  # each possible answer, and the outcome it would prove


@dataclass(frozen=True, slots=True)
class Contradiction:
    rules: tuple[str, ...]
    facts: tuple[Fact, ...]


@dataclass(frozen=True, slots=True)
class Escalate:
    reason: str


type Decision = Decided | NeedInfo | Contradiction | Escalate


def outcome_expr(o: Outcome) -> Expr:
    parts = tuple(Cmp("eq", Var(v), lit) for v, lit in o.assignment)
    return parts[0] if len(parts) == 1 else And(parts)


def fact_assertions(fs: Iterable[Fact]) -> list[tuple[Label, Expr]]:
    """One tracked `var == value` per distinct fact."""
    return list(dict.fromkeys(fact(f.var, f.value) for f in fs))


def _rule_ids(c: Compiled, core: frozenset[Label]) -> tuple[str, ...]:
    return tuple(r.id for r in c.policy.rules if RuleLabel(r.id) in core)


def _facts_in(core: frozenset[Label], fs: Sequence[Fact]) -> tuple[Fact, ...]:
    return tuple(f for f in fs if FactLabel(f.var, f.value) in core)


def _variable(c: Compiled, name: str) -> Variable:
    return next(v for v in c.policy.variables if v.name == name)


def _needs_confirmation(c: Compiled, f: Fact) -> bool:
    role = _variable(c, f.var).role
    return isinstance(f.provenance, Volunteered) and isinstance(role, Ask) and role.confirm_volunteered


def _first_proven(c: Compiled, fs: Sequence[Fact]) -> tuple[Outcome, frozenset[Label]] | None:
    for o in c.policy.outcomes:
        verdict = classify(c, outcome_expr(o), fact_assertions(fs))
        if isinstance(verdict, Proven):
            return o, verdict.core
    return None


def _answers(v: Variable) -> tuple[Lit, ...]:
    match v.sort:
        case BoolSort():
            return (BoolLit(True), BoolLit(False))
        case EnumSort(name, values):
            return tuple(EnumLit(name, x) for x in values)
        case _:
            return ()  # Int and Real answers can't be enumerated


def what_if(c: Compiled, firm: Sequence[Fact], var: str) -> tuple[tuple[Lit, str | None], ...]:
    out: list[tuple[Lit, str | None]] = []
    for value in _answers(_variable(c, var)):
        hit = _first_proven(c, [*firm, Fact(var, value, Answered("", ""))])
        out.append((value, hit[0].name if hit else None))
    return tuple(out)


def _question(c: Compiled, firm: Sequence[Fact], every: Sequence[Fact], unclear: frozenset[str]) -> Decision:
    known = {f.var for f in firm}
    used = frozenset().union(*(free_vars(rule_expr(r)) for r in c.policy.rules))
    candidates = [v for v in c.policy.variables
                  if isinstance(v.role, Ask) and v.name not in known and v.name in used]
    if not candidates:
        return Escalate("no outcome can be proven and there is nothing left to ask")
    tables = [what_if(c, firm, v.name) for v in candidates]
    scores = [sum(o is not None for _, o in t) for t in tables]
    best = max(range(len(candidates)), key=lambda i: (scores[i], -i))
    v, role = candidates[best], candidates[best].role
    assert isinstance(role, Ask)
    reason: Reason = ("unclear" if v.name in unclear
                      else "confirm" if any(f.var == v.name for f in every) else "missing")
    return NeedInfo(v.name, role.question, reason, tables[best])


def firm_facts(c: Compiled, fs: Facts) -> tuple[Fact, ...]:
    """The facts a decision may rest on: all of them except volunteered ones that still need confirming."""
    return tuple(f for f in all_facts(fs) if not _needs_confirmation(c, f))


def decide(c: Compiled, fs: Facts, *, unclear: frozenset[str] = frozenset()) -> Decision:
    """`unclear`: variables whose last answer couldn't be read, so the question is asked again."""
    every = all_facts(fs)
    match check(c, fact_assertions(every)):
        case Unsat(core):
            return Contradiction(_rule_ids(c, core), _facts_in(core, every))
        case Unknown(reason):
            return Escalate(f"the solver gave up: {reason}")
        case Sat():
            pass
        case other:
            assert_never(other)
    firm = firm_facts(c, fs)
    hit = _first_proven(c, firm)
    if hit:
        o, core = hit
        return Decided(o.name, _rule_ids(c, core), _facts_in(core, firm))
    hit = _first_proven(c, every)
    if hit:
        pending = [f for f in _facts_in(hit[1], every) if _needs_confirmation(c, f)]
        if pending:
            var = pending[0].var
            role = _variable(c, var).role
            assert isinstance(role, Ask)
            return NeedInfo(var, role.question, "confirm", what_if(c, firm, var))
    return _question(c, firm, every, unclear)
