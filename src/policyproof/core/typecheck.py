"""Sorts of expressions and well-formedness of policies.

`check_policy` is the smart constructor for `CheckedPolicy`: it reports every problem at once, and a policy that
passes is safe to compile and evaluate (no unknown names, no sort errors).
"""
from __future__ import annotations

import re
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from typing import assert_never

from returns.result import Failure, Result, Success

from policyproof.core._result import errors, sequence
from policyproof.core.syntax import (
    BOOL,
    INT,
    REAL,
    And,
    Arith,
    BoolLit,
    BoolSort,
    CheckedPolicy,
    Cmp,
    Constraint,
    Define,
    EnumLit,
    EnumSort,
    Expr,
    Iff,
    Implies,
    In,
    IntLit,
    IntSort,
    Not,
    Or,
    Policy,
    RealLit,
    RealSort,
    Sort,
    Var,
    When,
)

NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")


@dataclass(frozen=True, slots=True)
class Signature:
    """The names an expression may use: enum sorts by name, and each variable's sort."""

    sorts: Mapping[str, EnumSort]
    variables: Mapping[str, Sort]


def signature(p: Policy) -> Signature:
    return Signature({s.name: s for s in p.sorts}, {v.name: v.sort for v in p.variables})


# ---- errors


@dataclass(frozen=True, slots=True)
class UnknownName:
    name: str
    where: str


@dataclass(frozen=True, slots=True)
class UnknownValue:
    sort: str
    value: str
    where: str


@dataclass(frozen=True, slots=True)
class SortMismatch:
    expected: str
    got: Sort
    where: str


@dataclass(frozen=True, slots=True)
class BadArity:
    op: str
    got: int
    where: str


@dataclass(frozen=True, slots=True)
class Duplicate:
    kind: str
    name: str


@dataclass(frozen=True, slots=True)
class BadName:
    name: str


type SortError = UnknownName | UnknownValue | SortMismatch | BadArity | Duplicate | BadName


def sort_name(s: Sort) -> str:
    match s:
        case BoolSort():
            return "Bool"
        case IntSort():
            return "Int"
        case RealSort():
            return "Real"
        case EnumSort(name, _):
            return name
        case _:
            assert_never(s)


# ---- expressions


def sort_of(sig: Signature, e: Expr, where: str = "") -> Result[Sort, SortError]:
    match e:
        case BoolLit():
            return Success(BOOL)
        case IntLit():
            return Success(INT)
        case RealLit():
            return Success(REAL)
        case EnumLit(sort, value):
            if sort not in sig.sorts:
                return Failure(UnknownName(sort, where))
            s = sig.sorts[sort]
            return Success(s) if value in s.values else Failure(UnknownValue(sort, value, where))
        case Var(name):
            return Success(sig.variables[name]) if name in sig.variables else Failure(UnknownName(name, where))
        case Not(arg):
            return _expect(sig, arg, BOOL, where)
        case And(args) | Or(args):
            return sequence(_expect(sig, a, BOOL, where) for a in args).map(lambda _: BOOL)
        case Implies(lhs, rhs) | Iff(lhs, rhs):
            return _expect(sig, lhs, BOOL, where).bind(lambda _: _expect(sig, rhs, BOOL, where))
        case Cmp(op, lhs, rhs):
            return sort_of(sig, lhs, where).bind(lambda s: _cmp(sig, op, s, rhs, where))
        case Arith(op, args):
            if len(args) < 1 or (op == "sub" and len(args) != 2):
                return Failure(BadArity(op, len(args), where))
            return sort_of(sig, args[0], where).bind(lambda s: _numeric(s, where)).bind(
                lambda s: sequence(_expect(sig, a, s, where) for a in args[1:]).map(lambda _: s))
        case In(arg, values):
            return sort_of(sig, arg, where).bind(
                lambda s: sequence(_expect(sig, v, s, where) for v in values).map(lambda _: BOOL))
        case _:
            assert_never(e)


def _expect(sig: Signature, e: Expr, want: Sort, where: str) -> Result[Sort, SortError]:
    return sort_of(sig, e, where).bind(
        lambda s: Success(s) if s == want else Failure(SortMismatch(sort_name(want), s, where)))


def _numeric(s: Sort, where: str) -> Result[Sort, SortError]:
    return Success(s) if s in (INT, REAL) else Failure(SortMismatch("Int or Real", s, where))


def _cmp(sig: Signature, op: str, s: Sort, rhs: Expr, where: str) -> Result[Sort, SortError]:
    ordered = _numeric(s, where) if op in ("lt", "le", "gt", "ge") else Success(s)
    return ordered.bind(lambda _: _expect(sig, rhs, s, where)).map(lambda _: BOOL)


# ---- policies


def check_policy(p: Policy) -> Result[CheckedPolicy, tuple[SortError, ...]]:
    sig = signature(p)
    found: list[SortError] = []
    for kind, names in (("sort", [s.name for s in p.sorts]), ("variable", [v.name for v in p.variables]),
                        ("rule", [r.id for r in p.rules]), ("outcome", [o.name for o in p.outcomes])):
        found += [Duplicate(kind, n) for n, k in Counter(names).items() if k > 1]
    found += [BadName(n) for n in [*sig.sorts, *sig.variables] if not NAME.match(n)]
    found += [Duplicate("value", f"{s.name}.{v}") for s in p.sorts for v, k in Counter(s.values).items() if k > 1]
    for v in p.variables:
        if isinstance(v.sort, EnumSort) and sig.sorts.get(v.sort.name) != v.sort:
            found.append(UnknownName(v.sort.name, f"variables.{v.name}"))
    for r in p.rules:
        match r:
            case When(rid, when, then):
                found += errors(_expect(sig, when, BOOL, rid)) + errors(_expect(sig, then, BOOL, rid))
            case Define(rid, var, as_):
                if var not in sig.variables:
                    found.append(UnknownName(var, rid))
                else:
                    found += errors(_expect(sig, as_, sig.variables[var], rid))
            case Constraint(rid, expr):
                found += errors(_expect(sig, expr, BOOL, rid))
            case _:
                assert_never(r)
    for o in p.outcomes:
        for var, value in o.assignment:
            if var not in sig.variables:
                found.append(UnknownName(var, f"outcomes.{o.name}"))
            else:
                found += errors(_expect(sig, value, sig.variables[var], f"outcomes.{o.name}"))
    return Failure(tuple(found)) if found else Success(CheckedPolicy(p))
