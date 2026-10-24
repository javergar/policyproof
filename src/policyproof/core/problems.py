"""Every problem in a policy, each with its own example customer: what the studio walks an author through.

A problem is judged on complete inputs (every `system` and `ask` variable given) and shown as a minimal customer: only
the facts that matter. Two clashes are the same problem when the same rules clash, so a clash over a number (any
`daysLate` above 0) is found once, not once per number. See `docs/specs/2026-10-24-studio-design.md`.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import assert_never

from policyproof.core.semantics import free_vars, rule_expr
from policyproof.core.solver import (
    Compiled,
    FactLabel,
    Label,
    RuleLabel,
    Sat,
    Unknown,
    Unsat,
    check,
    decidable,
    fact,
    totality,
    undecided,
)
from policyproof.core.syntax import And, Ask, BoolLit, BoolSort, Cmp, EnumLit, EnumSort, Expr, Lit, Not, System, Var

type Customer = tuple[tuple[str, Lit], ...]  # sorted by variable name


@dataclass(frozen=True, slots=True)
class Says:
    """What one rule alone forces for the customer, on the variables that outcomes are made of."""

    rule: str
    forces: tuple[tuple[str, Lit], ...]


@dataclass(frozen=True, slots=True)
class Clash:
    """The rules can't all hold for this customer."""

    customer: Customer  # minimal: every completion of it clashes
    witness: Customer  # a complete input assignment that extends `customer`
    rules: tuple[str, ...]  # a minimal set of rules that can't all hold, in policy order
    says: tuple[Says, ...]  # one per rule in `rules`


@dataclass(frozen=True, slots=True)
class Gap:
    """The rules hold for this customer but prove no outcome."""

    customer: Customer  # minimal: no completion of it is decided
    witness: Customer
    rules: tuple[str, ...]  # the rules that mention a variable of `customer`, in policy order


@dataclass(frozen=True, slots=True)
class OutrightConflict:
    """The rules contradict each other with no facts at all."""

    rules: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class GaveUp:
    check: str
    reason: str


type Found = OutrightConflict | Clash | Gap | GaveUp


@dataclass(frozen=True, slots=True)
class Problems:
    found: tuple[Found, ...]  # an outright conflict alone if there is one; else clashes, then gaps, then GaveUp
    complete: bool  # False when the cap was hit or the solver gave up


DEFAULT_CAP = 25


def _inputs(c: Compiled) -> frozenset[str]:
    return frozenset(v.name for v in c.policy.variables if isinstance(v.role, System | Ask))


def _rule_assertions(c: Compiled, ids: Sequence[str]) -> list[tuple[Label, Expr]]:
    by_id = {r.id: r for r in c.policy.rules}
    return [(RuleLabel(i), rule_expr(by_id[i])) for i in ids]


def _ordered(c: Compiled, ids: frozenset[str] | set[str]) -> tuple[str, ...]:
    return tuple(r.id for r in c.policy.rules if r.id in ids)


def _unsat(c: Compiled, rules: Sequence[str], customer: Customer) -> bool:
    return isinstance(check(c, [*_rule_assertions(c, rules), *(fact(v, x) for v, x in customer)], rules=False), Unsat)


def _minimal_rules(c: Compiled, witness: Customer) -> tuple[str, ...] | Unknown:
    """A minimal set of rules that can't hold together with the witness (deletion from the unsat core), or Unknown
    when the solver can't settle the witness's ground check (nonlinear arithmetic, a timeout)."""
    result = check(c, [*_rule_assertions(c, [r.id for r in c.policy.rules]), *(fact(v, x) for v, x in witness)],
                   rules=False)
    if not isinstance(result, Unsat):
        return result if isinstance(result, Unknown) else Unknown("the clash's witness turned out consistent")
    kept = [label.id for label in result.core if isinstance(label, RuleLabel)]
    for rid in _ordered(c, set(kept)):
        trial = [r for r in kept if r != rid]
        if _unsat(c, trial, witness):
            kept = trial
    return _ordered(c, set(kept))


def _minimal_customer(c: Compiled, rules: Sequence[str], witness: Customer) -> Customer:
    """Drop every fact the clash doesn't need (deletion over the witness)."""
    kept = list(witness)
    for f in witness:
        trial = [x for x in kept if x != f]
        if _unsat(c, rules, tuple(trial)):
            kept = trial
    return tuple(kept)


def _finite(c: Compiled, var: str) -> tuple[Lit, ...]:
    match c.sorts[var]:
        case BoolSort():
            return (BoolLit(True), BoolLit(False))
        case EnumSort(name, values):
            return tuple(EnumLit(name, x) for x in values)
        case _:
            return ()


def _says(c: Compiled, rid: str, customer: Customer) -> Says:
    given = [*_rule_assertions(c, [rid]), *(fact(v, x) for v, x in customer)]
    if not isinstance(check(c, given, rules=False), Sat):
        return Says(rid, ())
    in_outcomes = {var for o in c.policy.outcomes for var, _ in o.assignment}
    shown = [v.name for v in c.policy.variables if v.name in in_outcomes]
    forced: list[tuple[str, Lit]] = []
    for var in shown:
        for value in _finite(c, var):
            other = (FactLabel(var, value), Not(Cmp("eq", Var(var), value)))
            if isinstance(check(c, [*given, other], rules=False), Unsat):
                forced.append((var, value))
    return Says(rid, tuple(forced))


def _conj(customer: Customer) -> Expr:
    parts = tuple(Cmp("eq", Var(v), x) for v, x in customer)
    return parts[0] if len(parts) == 1 else And(parts)


def _clashes(c: Compiled, cap: int) -> tuple[list[Found], bool]:
    inputs, found, seen = _inputs(c), [], []
    for _ in range(cap):
        match totality(c, inputs, blocked=seen):
            case Unsat():
                return found, True
            case Unknown(reason):
                return [*found, GaveUp("clashes", reason)], False
            case Sat(model):
                witness = tuple(sorted(model.items()))
                rules = _minimal_rules(c, witness)
                if isinstance(rules, Unknown):
                    return [*found, GaveUp("clashes", rules.reason)], False
                customer = _minimal_customer(c, rules, witness)
                found.append(Clash(customer, witness, rules, tuple(_says(c, r, customer) for r in rules)))
                seen.append(frozenset(rules))
            case other:
                assert_never(other)
    return found, False


def _minimal_gap(c: Compiled, inputs: frozenset[str], witness: Customer) -> Customer:
    """Drop a fact when no completion of the remaining facts is decided."""
    kept = list(witness)
    for f in witness:
        trial = [x for x in kept if x != f]
        if isinstance(decidable(c, inputs, given=[Cmp("eq", Var(v), x) for v, x in trial]), Unsat):
            kept = trial
    return tuple(kept)


def _gaps(c: Compiled, cap: int) -> tuple[list[Found], bool]:
    inputs, found, blocked = _inputs(c), [], []
    for _ in range(cap):
        match undecided(c, inputs, blocked=blocked):
            case Unsat():
                return found, True
            case Unknown(reason):
                return [*found, GaveUp("gaps", reason)], False
            case Sat(model):
                witness = tuple(sorted(model.items()))
                customer = _minimal_gap(c, inputs, witness)
                names = {v for v, _ in customer}
                rules = tuple(r.id for r in c.policy.rules if free_vars(rule_expr(r)) & names)
                found.append(Gap(customer, witness, rules))
                # integers would give one gap per number: block the Bool and enum part when there is one
                finite = tuple((v, x) for v, x in customer if isinstance(x, BoolLit | EnumLit))
                blocked.append(_conj(finite or customer) if customer else BoolLit(True))
            case other:
                assert_never(other)
    return found, False


def problems(c: Compiled, *, cap: int = DEFAULT_CAP) -> Problems:
    match check(c, []):
        case Unsat(core):
            rules = _ordered(c, {label.id for label in core if isinstance(label, RuleLabel)})
            for rid in rules:
                trial = [r for r in rules if r != rid]
                if _unsat(c, trial, ()):
                    rules = tuple(trial)
            return Problems((OutrightConflict(rules),), True)
        case Unknown(reason):
            return Problems((GaveUp("consistency", reason),), False)
        case Sat():
            pass
        case other:
            assert_never(other)
    clashes, clashes_done = _clashes(c, cap)
    gaps, gaps_done = _gaps(c, cap)
    every = [*clashes, *gaps]
    ordered = [f for f in every if not isinstance(f, GaveUp)] + [f for f in every if isinstance(f, GaveUp)]
    return Problems(tuple(ordered), clashes_done and gaps_done)


def _known(c: Compiled, customer: Customer) -> list[Expr]:
    """The customer's facts about variables `c` still has as inputs: a fix may have dropped or added some."""
    inputs = _inputs(c)
    return [Cmp("eq", Var(v), x) for v, x in customer if v in inputs]


def still_a_problem(c: Compiled, f: Clash | Gap) -> bool:
    """Whether a problem found on some version of a policy is still a problem on `c`, judged over every completion of
    its minimal customer: the author was shown that customer, not one complete witness, and a fix may add a question
    no earlier fact answers.

    A clash stays when the rules still can't hold for some completion; a gap stays when some completion is still
    undecided. When the solver gives up, the problem is kept."""
    match f:
        case Clash(customer=customer):
            return not isinstance(totality(c, _inputs(c), given=_known(c, customer)), Unsat)
        case Gap(customer=customer):
            return not isinstance(undecided(c, _inputs(c), given=_known(c, customer)), Unsat)
        case _:
            assert_never(f)


def decides(c: Compiled, customer: Customer, outcome: str) -> bool:
    """Whether every completion of the customer meets the rules and proves `outcome` (and at least one does)."""
    given = _known(c, customer)
    inputs = _inputs(c)
    return (isinstance(decidable(c, inputs, given=given, outcomes=[outcome]), Sat)
            and isinstance(undecided(c, inputs, given=given, outcomes=[outcome]), Unsat)
            and isinstance(totality(c, inputs, given=given), Unsat))


def _rules_of(f: Found) -> frozenset[str]:
    match f:
        case OutrightConflict(rules) | Clash(rules=rules) | Gap(rules=rules):
            return frozenset(rules)
        case GaveUp():
            return frozenset()
        case _:
            assert_never(f)


def groups(found: Sequence[Found]) -> tuple[tuple[int, ...], ...]:
    """Indices of problems connected through shared rules, each group in order, groups ordered by first index."""
    out: list[list[int]] = []
    for i, f in enumerate(found):
        rules = _rules_of(f)
        touching = [g for g in out if any(_rules_of(found[j]) & rules for j in g)]
        merged = sorted([j for g in touching for j in g] + [i])
        out = [g for g in out if g not in touching] + [merged]
    return tuple(sorted((tuple(g) for g in out), key=lambda g: g[0]))
