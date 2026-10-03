"""Deciding: the first outcome the facts prove, or the one question that settles it.

0. Facts must name known, non-derived variables with values of the right sort, or the result is `InvalidFacts`.
1. The rules and the firm facts must be consistent, or the result is a `Contradiction` naming the rules and facts.
   Firm facts: anything from a system; answers to a question about an askable variable; and volunteered facts about
   askable variables that don't need confirmation. Customers can't supply system facts: what they say about one is
   never firm.
2. The first outcome (in policy order) proven from the firm facts is `Decided`. If the solver gives up on an earlier
   outcome, the result is `Escalate`: a later outcome is never decided past one that might hold.
3. If an outcome is proven only with a volunteered fact, that fact is confirmed first: `NeedInfo(reason="confirm")`.
4. Otherwise the policy asks about the askable variable whose answers decide the most outcomes (the what-if table),
   ties broken by policy order; Int and Real questions (whose answers can't be enumerated) only when nothing else
   is left. With nothing left to ask, or no outcomes at all: `Escalate`.
"""
from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Literal, assert_never

from returns.pipeline import is_successful

from policyproof.core.facts import Answered, Fact, Facts, FromSystem, Volunteered, all_facts
from policyproof.core.prove import Proven, Undetermined, classify
from policyproof.core.semantics import free_vars, rule_expr
from policyproof.core.solver import Compiled, FactLabel, Label, RuleLabel, Sat, Unknown, Unsat, check, fact
from policyproof.core.syntax import (
    And,
    Ask,
    BoolLit,
    BoolSort,
    Cmp,
    Derived,
    EnumLit,
    EnumSort,
    Expr,
    Lit,
    Outcome,
    Var,
    Variable,
)
from policyproof.core.typecheck import signature, sort_name, sort_of

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


@dataclass(frozen=True, slots=True)
class InvalidFacts:
    """Facts that don't fit the policy: unknown or derived variables, or values of the wrong sort."""

    errors: tuple[str, ...]


type Decision = Decided | NeedInfo | Contradiction | Escalate | InvalidFacts


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


def _is_firm(c: Compiled, f: Fact) -> bool:
    role = _variable(c, f.var).role
    match f.provenance:
        case FromSystem():
            return True
        case Answered():
            return isinstance(role, Ask)
        case Volunteered():
            return isinstance(role, Ask) and not role.confirm_volunteered
        case _:
            assert_never(f.provenance)


def fact_errors(c: Compiled, fs: Facts) -> tuple[str, ...]:
    sig = signature(c.policy)
    found: list[str] = []
    for f in all_facts(fs):
        if f.var not in sig.variables:
            found.append(f"unknown variable {f.var!r}")
        elif isinstance(_variable(c, f.var).role, Derived):
            found.append(f"{f.var} is derived by the rules; it can't be given as a fact")
        else:
            got = sort_of(sig, f.value, f.var)
            if not is_successful(got):
                found.append(f"{f.var}: {got.failure()}")
            elif got.unwrap() != sig.variables[f.var]:
                found.append(f"{f.var} is {sort_name(sig.variables[f.var])}, not {sort_name(got.unwrap())}")
    return tuple(found)


@dataclass(frozen=True, slots=True)
class _Hit:
    outcome: Outcome
    core: frozenset[Label]


@dataclass(frozen=True, slots=True)
class _GaveUp:
    outcome: str
    reason: str


def _first_proven(c: Compiled, fs: Sequence[Fact]) -> _Hit | _GaveUp | None:
    """The first outcome the facts prove; or the first one the solver couldn't settle, which blocks later ones."""
    for o in c.policy.outcomes:
        verdict = classify(c, outcome_expr(o), fact_assertions(fs))
        if isinstance(verdict, Proven):
            return _Hit(o, verdict.core)
        if isinstance(verdict, Undetermined):
            return _GaveUp(o.name, verdict.reason)
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
        out.append((value, hit.outcome.name if isinstance(hit, _Hit) else None))
    return tuple(out)


def _question(c: Compiled, firm: Sequence[Fact], every: Sequence[Fact], unclear: frozenset[str]) -> Decision:
    known = {f.var for f in firm}
    used = frozenset().union(*(free_vars(rule_expr(r)) for r in c.policy.rules))
    candidates = [v for v in c.policy.variables
                  if isinstance(v.role, Ask) and v.name not in known and v.name in used]
    enumerable = [v for v in candidates if _answers(v)]
    candidates = enumerable or candidates
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
    """The facts a decision may rest on (see the module docstring). Assumes `fact_errors` found nothing."""
    return tuple(f for f in all_facts(fs) if _is_firm(c, f))


def decide(c: Compiled, fs: Facts, *, unclear: frozenset[str] = frozenset()) -> Decision:
    """`unclear`: variables whose last answer couldn't be read, so the question is asked again."""
    invalid = fact_errors(c, fs)
    if invalid:
        return InvalidFacts(invalid)
    if not c.policy.outcomes:
        return Escalate("the policy has no outcomes")
    every, firm = all_facts(fs), firm_facts(c, fs)
    match check(c, fact_assertions(firm)):
        case Unsat(core):
            return Contradiction(_rule_ids(c, core), _facts_in(core, firm))
        case Unknown(reason):
            return Escalate(f"the solver gave up: {reason}")
        case Sat():
            pass
        case other:
            assert_never(other)
    match _first_proven(c, firm):
        case _Hit(o, core):
            return Decided(o.name, _rule_ids(c, core), _facts_in(core, firm))
        case _GaveUp(name, reason):
            return Escalate(f"the solver gave up on outcome {name}: {reason}")
        case None:
            pass
    pending = [f for f in every if _needs_confirmation(c, f)]
    hit = _first_proven(c, [*firm, *pending]) if pending else None
    if isinstance(hit, _Hit):
        used = [f for f in _facts_in(hit.core, every) if _needs_confirmation(c, f)]
        if used:
            var = used[0].var
            role = _variable(c, var).role
            assert isinstance(role, Ask)
            return NeedInfo(var, role.question, "confirm", what_if(c, firm, var))
    return _question(c, firm, every, unclear)
