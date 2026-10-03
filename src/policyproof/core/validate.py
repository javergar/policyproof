"""Validation: is the policy sound enough to decide with? Run it before publishing; `gate` is the release check."""
from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from itertools import combinations
from typing import Literal, assert_never

from returns.result import Failure, Result, Success

from policyproof.core.semantics import free_vars, rule_expr
from policyproof.core.solver import Compiled, Model, RuleLabel, Sat, Unknown, Unsat, check, fact, totality
from policyproof.core.syntax import (
    Ask,
    BoolLit,
    BoolSort,
    Constraint,
    Define,
    Derived,
    EnumLit,
    EnumSort,
    Lit,
    Rule,
    System,
    When,
)


@dataclass(frozen=True, slots=True)
class Conflict:
    """These rules contradict each other outright: no world satisfies them."""

    rules: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class NotTotal:
    """For these input values the rules leave no possible answer."""

    witness: Model


@dataclass(frozen=True, slots=True)
class ImpossibleInput:
    """The rules rule out a value that a system or the customer could supply."""

    var: str
    value: Lit


@dataclass(frozen=True, slots=True)
class UnreachableOutcome:
    outcome: str


@dataclass(frozen=True, slots=True)
class SolverGaveUp:
    check: str
    reason: str


@dataclass(frozen=True, slots=True)
class UnusedVariable:
    var: str


@dataclass(frozen=True, slots=True)
class NearDuplicate:
    a: str
    b: str


@dataclass(frozen=True, slots=True)
class DisjointGroups:
    """The rules fall into groups that share no variable: often one idea under two names."""

    groups: tuple[tuple[str, ...], ...]


@dataclass(frozen=True, slots=True)
class OverlappingOutcomes:
    """Both outcomes can hold at once, so the decision depends on their order (the earlier one wins)."""

    first: str
    second: str


@dataclass(frozen=True, slots=True)
class ConstraintRule:
    rule: str


@dataclass(frozen=True, slots=True)
class DefinitionToReview:
    rule: str


type Finding = (Conflict | NotTotal | ImpossibleInput | UnreachableOutcome | SolverGaveUp | UnusedVariable
                | NearDuplicate | DisjointGroups | OverlappingOutcomes | ConstraintRule | DefinitionToReview)
type Severity = Literal["error", "warning", "review"]
SEVERITY_ORDER: dict[Severity, int] = {"error": 0, "warning": 1, "review": 2}


def severity(f: Finding) -> Severity:
    match f:
        case Conflict() | NotTotal() | ImpossibleInput() | UnreachableOutcome() | SolverGaveUp():
            return "error"
        case UnusedVariable() | NearDuplicate() | DisjointGroups():
            return "warning"
        case OverlappingOutcomes() | ConstraintRule() | DefinitionToReview():
            return "review"
        case _:
            assert_never(f)


def _rule_vars(r: Rule) -> frozenset[str]:
    return free_vars(rule_expr(r))


def _structural(c: Compiled) -> list[Finding]:
    p = c.policy
    found: list[Finding] = []
    for r in p.rules:
        match r:
            case Constraint():
                found.append(ConstraintRule(r.id))
            case Define():
                found.append(DefinitionToReview(r.id))
            case When():
                pass
            case _:
                assert_never(r)
    used = frozenset().union(*(_rule_vars(r) for r in p.rules), *({v for v, _ in o.assignment} for o in p.outcomes))
    found += [UnusedVariable(v.name) for v in p.variables if v.name not in used]
    names = [v.name for v in p.variables]
    found += [NearDuplicate(a, b) for a, b in combinations(names, 2) if _near(a, b)]
    groups = _groups(p.rules)
    if len(groups) > 1:
        found.append(DisjointGroups(groups))
    return found


STOP_WORDS = {"is", "has", "was", "the", "a", "an", "of", "for", "to", "be"}


def _tokens(name: str) -> frozenset[str]:
    words = re.findall(r"[A-Z]?[a-z0-9]+|[A-Z]+(?![a-z])", name)
    return frozenset(w.lower() for w in words) - STOP_WORDS


def _near(a: str, b: str) -> bool:
    return _tokens(a) == _tokens(b) or SequenceMatcher(None, a.lower(), b.lower()).ratio() >= 0.85


def _groups(rules: tuple[Rule, ...]) -> tuple[tuple[str, ...], ...]:
    """Rules connected by shared variables, each group in policy order."""
    groups: list[tuple[set[str], list[str]]] = []
    for r in rules:
        names = set(_rule_vars(r))
        touching = [g for g in groups if g[0] & names] if names else []
        merged = (names.union(*(g[0] for g in touching)), [rid for g in touching for rid in g[1]] + [r.id])
        groups = [g for g in groups if g not in touching] + [merged]
    order = {r.id: i for i, r in enumerate(rules)}
    return tuple(sorted((tuple(sorted(ids, key=order.__getitem__)) for _, ids in groups), key=lambda g: order[g[0]]))


def _finite_values(v_sort: BoolSort | EnumSort) -> tuple[Lit, ...]:
    match v_sort:
        case BoolSort():
            return (BoolLit(False), BoolLit(True))
        case EnumSort(name, values):
            return tuple(EnumLit(name, x) for x in values)
        case _:
            assert_never(v_sort)


def _logical(c: Compiled) -> list[Finding]:
    p = c.policy
    found: list[Finding] = []
    inputs = frozenset(v.name for v in p.variables if isinstance(v.role, System | Ask))
    match totality(c, inputs):
        case Sat(witness):
            found.append(NotTotal(witness))
        case Unknown(reason):
            found.append(SolverGaveUp("totality", reason))
        case Unsat():
            pass
        case other:
            assert_never(other)
    for v in p.variables:
        if isinstance(v.role, Derived) or not isinstance(v.sort, BoolSort | EnumSort):
            continue
        found += [ImpossibleInput(v.name, x) for x in _finite_values(v.sort)
                  if isinstance(check(c, [fact(v.name, x)]), Unsat)]
    assignments = {o.name: [fact(var, value) for var, value in o.assignment] for o in p.outcomes}
    found += [UnreachableOutcome(name) for name, a in assignments.items() if isinstance(check(c, a), Unsat)]
    found += [OverlappingOutcomes(a, b) for a, b in combinations(assignments, 2)
              if isinstance(check(c, assignments[a] + assignments[b]), Sat)]
    return found


def validate(c: Compiled) -> tuple[Finding, ...]:
    """Every finding, errors first. Logical checks are skipped when the rules contradict each other outright."""
    order = {r.id: i for i, r in enumerate(c.policy.rules)}
    match check(c, []):
        case Unsat(core):
            ids = sorted((label.id for label in core if isinstance(label, RuleLabel)), key=order.__getitem__)
            found: list[Finding] = [Conflict(tuple(ids))]
        case Unknown(reason):
            found = [SolverGaveUp("consistency", reason)]
        case Sat():
            found = _logical(c)
        case other:
            assert_never(other)
    return tuple(sorted(found + _structural(c), key=lambda f: SEVERITY_ORDER[severity(f)]))


def gate(c: Compiled) -> Result[Compiled, tuple[Finding, ...]]:
    """Success when there are no errors; otherwise every finding."""
    report = validate(c)
    return Failure(report) if any(severity(f) == "error" for f in report) else Success(c)
