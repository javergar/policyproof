"""Z3 as a compile target. The only module that imports z3.

`compile` builds one Z3 context per policy, so enum names never clash across policies. `check` makes a fresh solver
for every call and returns plain values (models as literals, unsat cores as labels), so callers stay pure: the same
inputs always give the same answer.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from fractions import Fraction
from functools import reduce
from typing import assert_never, cast

import z3

from policyproof.core.render import smt_name
from policyproof.core.semantics import free_vars, rule_expr
from policyproof.core.syntax import (
    And,
    Arith,
    BoolLit,
    BoolSort,
    CheckedPolicy,
    Cmp,
    EnumLit,
    EnumSort,
    Expr,
    Iff,
    Implies,
    In,
    IntLit,
    IntSort,
    Lit,
    Not,
    Or,
    Outcome,
    RealLit,
    RealSort,
    Rule,
    Sort,
    Var,
)
from policyproof.core.typecheck import signature

# ---- labels for unsat cores


@dataclass(frozen=True, slots=True)
class RuleLabel:
    id: str


@dataclass(frozen=True, slots=True)
class FactLabel:
    var: str
    value: Lit


@dataclass(frozen=True, slots=True)
class ExtraLabel:
    name: str


type Label = RuleLabel | FactLabel | ExtraLabel

# ---- results

type Model = Mapping[str, Lit]


@dataclass(frozen=True, slots=True)
class Sat:
    model: Model


@dataclass(frozen=True, slots=True)
class Unsat:
    core: frozenset[Label]


@dataclass(frozen=True, slots=True)
class Unknown:
    reason: str


type SatResult = Sat | Unsat | Unknown

# ---- compilation


@dataclass(frozen=True, slots=True)
class Compiled:
    policy: CheckedPolicy
    ctx: z3.Context
    variables: Mapping[str, z3.ExprRef]
    sorts: Mapping[str, Sort]
    values: Mapping[tuple[str, str], z3.ExprRef]
    rules: Mapping[str, z3.BoolRef]
    timeout_ms: int  # every solver call gives up after this long and reports Unknown


DEFAULT_TIMEOUT_MS = 10_000


def _declare(name: str, sort: Sort, ctx: z3.Context, enums: Mapping[str, z3.DatatypeSortRef]) -> z3.ExprRef:
    match sort:
        case BoolSort():
            return z3.Bool(name, ctx)
        case IntSort():
            return z3.Int(name, ctx)
        case RealSort():
            return z3.Real(name, ctx)
        case EnumSort(sname, _):
            return z3.Const(name, enums[sname])
        case _:
            assert_never(sort)


def compile(p: CheckedPolicy, *, timeout_ms: int = DEFAULT_TIMEOUT_MS) -> Compiled:
    ctx = z3.Context()
    enums: dict[str, z3.DatatypeSortRef] = {}
    values: dict[tuple[str, str], z3.ExprRef] = {}
    for s in p.sorts:
        zsort, consts = z3.EnumSort(s.name, [smt_name(s.name, v) for v in s.values], ctx=ctx)
        enums[s.name] = zsort
        values |= {(s.name, v): c for v, c in zip(s.values, consts, strict=True)}
    sig = signature(p)
    variables = {n: _declare(n, s, ctx, enums) for n, s in sig.variables.items()}
    c = Compiled(p, ctx, variables, dict(sig.variables), values, {}, timeout_ms)
    rules = {r.id: rule_formula(c, r) for r in p.rules}
    return Compiled(p, ctx, variables, dict(sig.variables), values, rules, timeout_ms)


def _solver(c: Compiled) -> z3.Solver:
    s = z3.Solver(ctx=c.ctx)
    s.set("timeout", c.timeout_ms)
    return s


def rule_formula(c: Compiled, r: Rule) -> z3.BoolRef:
    return _bool(to_z3(c, rule_expr(r)))


def to_z3(c: Compiled, e: Expr) -> z3.ExprRef:
    match e:
        case BoolLit(v):
            return z3.BoolVal(v, c.ctx)
        case IntLit(v):
            return z3.IntVal(v, c.ctx)
        case RealLit(v):
            return z3.RatVal(v.numerator, v.denominator, c.ctx)
        case EnumLit(sort, value):
            return c.values[(sort, value)]
        case Var(name):
            return c.variables[name]
        case Not(arg):
            return z3.Not(to_z3(c, arg), c.ctx)
        case And(args):
            return z3.And(*[to_z3(c, a) for a in args], c.ctx)
        case Or(args):
            return z3.Or(*[to_z3(c, a) for a in args], c.ctx)
        case Implies(lhs, rhs):
            return z3.Implies(to_z3(c, lhs), to_z3(c, rhs), c.ctx)
        case Iff(lhs, rhs):
            return _eq(to_z3(c, lhs), to_z3(c, rhs))
        case Cmp("eq", lhs, rhs):
            return _eq(to_z3(c, lhs), to_z3(c, rhs))
        case Cmp("ne", lhs, rhs):
            return z3.Not(_eq(to_z3(c, lhs), to_z3(c, rhs)), c.ctx)
        case Cmp(op, lhs, rhs):
            return ORDER[op](_arith(to_z3(c, lhs)), _arith(to_z3(c, rhs)))
        case Arith(op, args):
            return reduce(ARITH[op], [_arith(to_z3(c, a)) for a in args])
        case In(arg, values):
            x = to_z3(c, arg)
            return z3.Or(*[_eq(x, to_z3(c, v)) for v in values], c.ctx)
        case _:
            assert_never(e)


def _eq(a: z3.ExprRef, b: z3.ExprRef) -> z3.BoolRef:
    return cast(z3.BoolRef, a == b)  # z3 overloads == to build a term, which checkers read as bool


def _bool(x: z3.ExprRef) -> z3.BoolRef:
    return cast(z3.BoolRef, x)  # rule bodies of well-typed policies are Boolean terms


def _arith(x: z3.ExprRef) -> z3.ArithRef:
    return cast(z3.ArithRef, x)  # only well-typed policies are compiled: these operands are Int or Real terms


ORDER: dict[str, Callable[[z3.ArithRef, z3.ArithRef], z3.BoolRef]] = {
    "lt": lambda x, y: x < y, "le": lambda x, y: x <= y, "gt": lambda x, y: x > y, "ge": lambda x, y: x >= y}
ARITH: dict[str, Callable[[z3.ArithRef, z3.ArithRef], z3.ArithRef]] = {
    "add": lambda x, y: x + y, "sub": lambda x, y: x - y, "mul": lambda x, y: x * y}


def _to_lit(c: Compiled, sort: Sort, v: z3.ExprRef) -> Lit:
    match sort:
        case BoolSort():
            return BoolLit(z3.is_true(v))
        case IntSort():
            return IntLit(v.as_long())  # ty: ignore[unresolved-attribute] - an IntNumRef once evaluated
        case RealSort():
            if z3.is_algebraic_value(v):  # an irrational value (e.g. the square root of 2): a close rational
                v = v.approx(20)  # ty: ignore[unresolved-attribute] - an AlgebraicNumRef
            return RealLit(Fraction(v.as_fraction()))  # ty: ignore[unresolved-attribute] - a RatNumRef
        case EnumSort(sname, _):
            return EnumLit(sname, str(v).removeprefix(f"{sname}."))
        case _:
            assert_never(sort)


def ground(c: Compiled, e: Expr, sort: Sort, env: Mapping[str, Lit]) -> Lit:
    """Z3's value of `e` with every variable replaced by its value in `env` (which must bind all of them)."""
    pairs = [(c.variables[n], to_z3(c, v)) for n, v in env.items() if n in c.variables]
    term = z3.substitute(to_z3(c, e), *pairs) if pairs else to_z3(c, e)
    return _to_lit(c, sort, z3.simplify(term))


TRACK = "track!"  # tracking literals; "!" can't occur in a policy name, so they never collide with a variable


def check(c: Compiled, assertions: Sequence[tuple[Label, Expr]], *, rules: bool = True) -> SatResult:
    """Satisfiability of the policy's rules (unless `rules=False`) together with `assertions`, each tracked by its
    label so an unsat core can be named."""
    s = _solver(c)
    labels: list[Label] = []
    tracked = [*((RuleLabel(rid), f) for rid, f in c.rules.items() if rules),
               *((label, to_z3(c, e)) for label, e in assertions)]
    for i, (label, formula) in enumerate(tracked):
        labels.append(label)
        s.assert_and_track(formula, z3.Bool(f"{TRACK}{i}", c.ctx))
    match s.check():
        case z3.sat:
            m = s.model()
            return Sat({n: _to_lit(c, c.sorts[n], m.eval(v, model_completion=True)) for n, v in c.variables.items()})
        case z3.unsat:
            return Unsat(frozenset(labels[int(str(t).removeprefix(TRACK))] for t in s.unsat_core()))
        case _:
            return Unknown(s.reason_unknown())


def fact(var: str, value: Lit) -> tuple[Label, Expr]:
    """The tracked assertion `var == value`."""
    return FactLabel(var, value), Cmp("eq", Var(var), value)


def _split(c: Compiled, inputs: frozenset[str]) -> tuple[list[z3.BoolRef], z3.BoolRef, list[z3.ExprRef]]:
    """The rules about inputs alone, the conjunction of the other rules, and the non-input variables."""
    domain = [r for r in c.policy.rules if free_vars(rule_expr(r)) <= inputs]
    rest = z3.And(*[c.rules[r.id] for r in c.policy.rules if r not in domain], c.ctx)
    others = [v for n, v in c.variables.items() if n not in inputs]
    return [c.rules[r.id] for r in domain], rest, others


def _exists(others: list[z3.ExprRef], f: z3.BoolRef) -> z3.BoolRef:
    return z3.Exists(others, f) if others else f


def _forall(others: list[z3.ExprRef], f: z3.BoolRef) -> z3.BoolRef:
    return z3.ForAll(others, f) if others else f


def _outcome(c: Compiled, o: Outcome) -> z3.BoolRef:
    return z3.And(*[_eq(c.variables[var], to_z3(c, lit)) for var, lit in o.assignment], c.ctx)


def _witness(c: Compiled, s: z3.Solver, inputs: frozenset[str]) -> SatResult:
    match s.check():
        case z3.sat:
            m = s.model()
            return Sat({n: _to_lit(c, c.sorts[n], m.eval(c.variables[n], model_completion=True))
                        for n in sorted(inputs)})
        case z3.unsat:
            return Unsat(frozenset())
        case _:
            return Unknown(s.reason_unknown())


def totality(c: Compiled, inputs: frozenset[str], *, blocked: Sequence[frozenset[str]] = ()) -> SatResult:
    """`Sat(witness)` when some values of `inputs` that meet the rules about inputs alone leave no values of the
    other variables that meet every rule: the policy has no answer for that case. `Unsat` when it always has one.

    Each `blocked` set of rule ids must be able to hold together for the witness, so a clash among exactly those rules
    is never found again (the problem finder enumerates distinct clashes this way)."""
    domain, rest, others = _split(c, inputs)
    s = _solver(c)
    s.add(*domain)
    s.add(_forall(others, z3.Not(rest, c.ctx)))
    for ids in blocked:
        s.add(_exists(others, z3.And(*[c.rules[i] for i in ids], c.ctx)))
    return _witness(c, s, inputs)


def undecided(c: Compiled, inputs: frozenset[str], *, blocked: Sequence[Expr] = ()) -> SatResult:
    """`Sat(witness)` when some values of `inputs` meet every rule yet prove no outcome: for each outcome, some values
    of the other variables meet the rules without it. `Unsat` when every case is decided, or there are no outcomes.
    Each `blocked` expression is ruled out for the witness."""
    if not c.policy.outcomes:
        return Unsat(frozenset())
    domain, rest, others = _split(c, inputs)
    s = _solver(c)
    s.add(*domain)
    s.add(_exists(others, rest))
    for o in c.policy.outcomes:
        s.add(_exists(others, z3.And(rest, z3.Not(_outcome(c, o)))))
    s.add(*[z3.Not(to_z3(c, b)) for b in blocked])
    return _witness(c, s, inputs)


def decidable(c: Compiled, inputs: frozenset[str], *, given: Sequence[Expr]) -> SatResult:
    """`Sat(witness)` when some values of `inputs` that meet `given` and every rule prove an outcome."""
    if not c.policy.outcomes:
        return Unsat(frozenset())
    domain, rest, others = _split(c, inputs)
    s = _solver(c)
    s.add(*domain)
    s.add(_exists(others, rest))
    s.add(*[to_z3(c, g) for g in given])
    s.add(z3.Or(*[_forall(others, z3.Implies(rest, _outcome(c, o))) for o in c.policy.outcomes], c.ctx))
    return _witness(c, s, inputs)
