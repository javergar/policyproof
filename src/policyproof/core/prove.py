"""Classifying a claim against a policy: proven, refuted, contingent, or the premises are inconsistent."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import assert_never

from policyproof.core.solver import (
    Compiled,
    ExtraLabel,
    Label,
    Model,
    Sat,
    Unknown,
    Unsat,
    check,
    fact,
)
from policyproof.core.syntax import Expr, Iff, Lit, Not


@dataclass(frozen=True, slots=True)
class Proven:
    """Every world allowed by the rules and premises makes the claim true. `core` names what the proof used."""

    core: frozenset[Label]


@dataclass(frozen=True, slots=True)
class Refuted:
    """No such world makes the claim true. `core` names what rules it out."""

    core: frozenset[Label]


@dataclass(frozen=True, slots=True)
class Contingent:
    """Some worlds make it true and some false: a witness of each."""

    when_true: Model
    when_false: Model


@dataclass(frozen=True, slots=True)
class Inconsistent:
    """The rules and premises contradict each other, so nothing can be concluded."""

    core: frozenset[Label]


@dataclass(frozen=True, slots=True)
class Undetermined:
    """The solver gave up (for example on non-linear arithmetic)."""

    reason: str


type Verdict = Proven | Refuted | Contingent | Inconsistent | Undetermined

CLAIM, NOT_CLAIM = ExtraLabel("claim"), ExtraLabel("negated claim")


def premises(given: Mapping[str, Lit] | None = None, exprs: Sequence[Expr] = ()) -> list[tuple[Label, Expr]]:
    """Tracked assertions: one `var == value` per given fact, then each expression as `premise[i]`."""
    return [*(fact(n, v) for n, v in (given or {}).items()),
            *((ExtraLabel(f"premise[{i}]"), e) for i, e in enumerate(exprs))]


def classify(c: Compiled, claim: Expr, assertions: Sequence[tuple[Label, Expr]] = (), *, rules: bool = True
             ) -> Verdict:
    match check(c, assertions, rules=rules):
        case Unsat(core):
            return Inconsistent(core)
        case Unknown(reason):
            return Undetermined(reason)
        case Sat():
            pass
        case other:
            assert_never(other)
    negated = check(c, [*assertions, (NOT_CLAIM, Not(claim))], rules=rules)
    if isinstance(negated, Unsat):
        return Proven(negated.core - {NOT_CLAIM})
    affirmed = check(c, [*assertions, (CLAIM, claim)], rules=rules)
    if isinstance(affirmed, Unsat):
        return Refuted(affirmed.core - {CLAIM})
    if isinstance(negated, Sat) and isinstance(affirmed, Sat):
        return Contingent(affirmed.model, negated.model)
    unknown = negated if isinstance(negated, Unknown) else affirmed
    return Undetermined(unknown.reason if isinstance(unknown, Unknown) else "unknown")


def entails(c: Compiled, given: Sequence[Expr], conclusion: Expr, *, rules: bool = True) -> bool:
    """`given` (with the rules, unless `rules=False`) proves `conclusion`, and `given` is consistent."""
    return isinstance(classify(c, conclusion, premises(exprs=given), rules=rules), Proven)


def equivalent(c: Compiled, a: Expr, b: Expr) -> bool:
    """`a` and `b` mean the same in every world, regardless of the policy's rules."""
    return isinstance(check(c, [(NOT_CLAIM, Not(Iff(a, b)))], rules=False), Unsat)
