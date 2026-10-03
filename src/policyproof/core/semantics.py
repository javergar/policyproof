"""The reference semantics: evaluation, substitution, free variables and simplification.

Independent of Z3 on purpose. The laws (compile soundness, simplification) are stated against `evaluate`, so Z3 is
checked against a few lines of plain Python rather than trusted.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from fractions import Fraction
from functools import reduce
from operator import add, mul, sub
from typing import assert_never

from returns.result import Failure, Result, Success

from policyproof.core._result import sequence
from policyproof.core.syntax import (
    And,
    Arith,
    BoolLit,
    Cmp,
    Constraint,
    Define,
    EnumLit,
    Expr,
    Iff,
    Implies,
    In,
    IntLit,
    Lit,
    Not,
    Or,
    RealLit,
    Rule,
    Var,
    When,
)

type Env = Mapping[str, Lit]


@dataclass(frozen=True, slots=True)
class Unbound:
    name: str


@dataclass(frozen=True, slots=True)
class Mismatch:
    expected: str
    got: Lit


type EvalError = Unbound | Mismatch


def _bool(e: Expr, env: Env) -> Result[bool, EvalError]:
    return evaluate(e, env).bind(lambda v: Success(v.value) if isinstance(v, BoolLit) else Failure(Mismatch("Bool", v)))


def _num(v: Lit) -> Result[int | Fraction, EvalError]:
    match v:
        case IntLit(n) | RealLit(n):
            return Success(n)
        case _:
            return Failure(Mismatch("Int or Real", v))


def _same_kind(vs: tuple[Lit, ...]) -> Result[tuple[Lit, ...], EvalError]:
    first = type(vs[0])
    odd = next((v for v in vs if type(v) is not first), None)
    return Failure(Mismatch(first.__name__.removesuffix("Lit"), odd)) if odd is not None else Success(vs)


def _arith(op: str, vs: tuple[Lit, ...]) -> Result[Lit, EvalError]:
    fn: Callable[[int | Fraction, int | Fraction], int | Fraction] = {"add": add, "sub": sub, "mul": mul}[op]
    return _same_kind(vs).bind(lambda same: sequence(_num(v) for v in same)).map(lambda ns: _wrap_num(
        vs[0], reduce(fn, ns)))


def _wrap_num(like: Lit, n: int | Fraction) -> Lit:
    return IntLit(int(n)) if isinstance(like, IntLit) else RealLit(Fraction(n))


def _compare(op: str, a: Lit, b: Lit) -> Result[bool, EvalError]:
    if op == "eq":
        return Success(a == b)
    if op == "ne":
        return Success(a != b)
    ordered: dict[str, Callable[[int | Fraction, int | Fraction], bool]] = {
        "lt": lambda x, y: x < y, "le": lambda x, y: x <= y, "gt": lambda x, y: x > y, "ge": lambda x, y: x >= y}
    return _num(a).bind(lambda x: _num(b).map(lambda y: ordered[op](x, y)))


def evaluate(e: Expr, env: Env) -> Result[Lit, EvalError]:
    """The value of `e` under `env`. Strict: every variable that occurs must be bound."""
    match e:
        case BoolLit() | IntLit() | RealLit() | EnumLit():
            return Success(e)
        case Var(name):
            return Success(env[name]) if name in env else Failure(Unbound(name))
        case Not(arg):
            return _bool(arg, env).map(lambda b: BoolLit(not b))
        case And(args):
            return sequence(_bool(a, env) for a in args).map(lambda bs: BoolLit(all(bs)))
        case Or(args):
            return sequence(_bool(a, env) for a in args).map(lambda bs: BoolLit(any(bs)))
        case Implies(lhs, rhs):
            return _bool(lhs, env).bind(lambda a: _bool(rhs, env).map(lambda b: BoolLit(not a or b)))
        case Iff(lhs, rhs):
            return _bool(lhs, env).bind(lambda a: _bool(rhs, env).map(lambda b: BoolLit(a == b)))
        case Cmp(op, lhs, rhs):
            return evaluate(lhs, env).bind(lambda a: evaluate(rhs, env).bind(
                lambda b: _compare(op, a, b))).map(BoolLit)
        case Arith(op, args):
            return sequence(evaluate(a, env) for a in args).bind(lambda vs: _arith(op, vs))
        case In(arg, values):
            return evaluate(arg, env).map(lambda v: BoolLit(v in values))
        case _:
            assert_never(e)


def rule_expr(r: Rule) -> Expr:
    """What a rule asserts, as one Boolean expression."""
    match r:
        case When(_, when, then):
            return Implies(when, then)
        case Define(_, var, as_):
            return Cmp("eq", Var(var), as_)
        case Constraint(_, expr):
            return expr
        case _:
            assert_never(r)


def substitute(e: Expr, env: Env) -> Expr:
    """`e` with every variable bound in `env` replaced by its value."""
    match e:
        case BoolLit() | IntLit() | RealLit() | EnumLit():
            return e
        case Var(name):
            return env.get(name, e)
        case Not(arg):
            return Not(substitute(arg, env))
        case And(args):
            return And(tuple(substitute(a, env) for a in args))
        case Or(args):
            return Or(tuple(substitute(a, env) for a in args))
        case Implies(lhs, rhs):
            return Implies(substitute(lhs, env), substitute(rhs, env))
        case Iff(lhs, rhs):
            return Iff(substitute(lhs, env), substitute(rhs, env))
        case Cmp(op, lhs, rhs):
            return Cmp(op, substitute(lhs, env), substitute(rhs, env))
        case Arith(op, args):
            return Arith(op, tuple(substitute(a, env) for a in args))
        case In(arg, values):
            return In(substitute(arg, env), values)
        case _:
            assert_never(e)


def free_vars(e: Expr) -> frozenset[str]:
    match e:
        case BoolLit() | IntLit() | RealLit() | EnumLit():
            return frozenset()
        case Var(name):
            return frozenset({name})
        case Not(arg) | In(arg, _):
            return free_vars(arg)
        case And(args) | Or(args) | Arith(_, args):
            return frozenset().union(*(free_vars(a) for a in args))
        case Implies(lhs, rhs) | Iff(lhs, rhs) | Cmp(_, lhs, rhs):
            return free_vars(lhs) | free_vars(rhs)
        case _:
            assert_never(e)


TRUE, FALSE = BoolLit(True), BoolLit(False)


def _is_lit(e: Expr) -> bool:
    return isinstance(e, BoolLit | IntLit | RealLit | EnumLit)


def _fold(e: Expr) -> Expr:
    """Evaluate a closed node to its literal; leave anything else as it is."""
    return evaluate(e, {}).value_or(e) if not free_vars(e) else e


def _junction(args: tuple[Expr, ...], unit: BoolLit, zero: BoolLit, build: type[And] | type[Or]) -> Expr:
    flat: list[Expr] = []
    for a in args:
        flat.extend(a.args if isinstance(a, build) else (a,))
    if zero in flat:
        return zero
    kept = tuple(dict.fromkeys(a for a in flat if a != unit))  # drop units and duplicates, keep order
    return unit if not kept else kept[0] if len(kept) == 1 else build(kept)


def _negate(e: Expr) -> Expr:
    match e:
        case BoolLit(v):
            return BoolLit(not v)
        case Not(arg):
            return arg
        case _:
            return Not(e)


def simplify(e: Expr) -> Expr:
    """An equivalent expression with constants folded and Boolean units, zeros and duplicates removed."""
    match e:
        case BoolLit() | IntLit() | RealLit() | EnumLit() | Var():
            return e
        case Not(arg):
            return _negate(simplify(arg))
        case And(args):
            return _junction(tuple(simplify(a) for a in args), TRUE, FALSE, And)
        case Or(args):
            return _junction(tuple(simplify(a) for a in args), FALSE, TRUE, Or)
        case Implies(lhs, rhs):
            a, b = simplify(lhs), simplify(rhs)
            if a == TRUE:
                return b
            if b == TRUE or a in (FALSE, b):
                return TRUE
            return _negate(a) if b == FALSE else Implies(a, b)
        case Iff(lhs, rhs):
            a, b = simplify(lhs), simplify(rhs)
            if a == b:
                return TRUE
            for x, y in ((a, b), (b, a)):
                if x == TRUE:
                    return y
                if x == FALSE:
                    return _negate(y)
            return Iff(a, b)
        case Cmp(op, lhs, rhs):
            a, b = simplify(lhs), simplify(rhs)
            if a == b and op in ("eq", "le", "ge"):
                return TRUE
            if a == b and op in ("ne", "lt", "gt"):
                return FALSE
            return _fold(Cmp(op, a, b))
        case Arith(op, args):
            return _fold(Arith(op, tuple(simplify(a) for a in args)))
        case In(arg, values):
            return _fold(In(simplify(arg), values))
        case _:
            assert_never(e)
