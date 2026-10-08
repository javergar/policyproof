"""The policy language as data: sorts, expressions, rules, variables, outcomes and policies.

Only data lives here. Every type is a frozen, slotted dataclass, and every union is closed, so a `match` over one ends
in `assert_never`. Literals are tagged (`BoolLit(True)` is not `IntLit(1)`), so equality is exact.
"""
from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from typing import Literal, NewType

# ---- sorts


@dataclass(frozen=True, slots=True)
class BoolSort:
    pass


@dataclass(frozen=True, slots=True)
class IntSort:
    pass


@dataclass(frozen=True, slots=True)
class RealSort:
    pass


@dataclass(frozen=True, slots=True)
class EnumSort:
    name: str
    values: tuple[str, ...]


type Sort = BoolSort | IntSort | RealSort | EnumSort

BOOL, INT, REAL = BoolSort(), IntSort(), RealSort()

# ---- literals (also the values expressions evaluate to)


@dataclass(frozen=True, slots=True)
class BoolLit:
    value: bool


@dataclass(frozen=True, slots=True)
class IntLit:
    value: int


@dataclass(frozen=True, slots=True)
class RealLit:
    value: Fraction


@dataclass(frozen=True, slots=True)
class EnumLit:
    sort: str
    value: str


type Lit = BoolLit | IntLit | RealLit | EnumLit

# ---- expressions


@dataclass(frozen=True, slots=True)
class Var:
    name: str


@dataclass(frozen=True, slots=True)
class Not:
    arg: Expr


@dataclass(frozen=True, slots=True)
class And:
    args: tuple[Expr, ...]


@dataclass(frozen=True, slots=True)
class Or:
    args: tuple[Expr, ...]


@dataclass(frozen=True, slots=True)
class Implies:
    lhs: Expr
    rhs: Expr


@dataclass(frozen=True, slots=True)
class Iff:
    lhs: Expr
    rhs: Expr


type CmpOp = Literal["eq", "ne", "lt", "le", "gt", "ge"]
CMP_OPS: tuple[CmpOp, ...] = ("eq", "ne", "lt", "le", "gt", "ge")


@dataclass(frozen=True, slots=True)
class Cmp:
    op: CmpOp
    lhs: Expr
    rhs: Expr


type ArithOp = Literal["add", "sub", "mul"]
ARITH_OPS: tuple[ArithOp, ...] = ("add", "sub", "mul")


@dataclass(frozen=True, slots=True)
class Arith:
    op: ArithOp
    args: tuple[Expr, ...]


@dataclass(frozen=True, slots=True)
class In:
    arg: Expr
    values: tuple[Lit, ...]


type Expr = BoolLit | IntLit | RealLit | EnumLit | Var | Not | And | Or | Implies | Iff | Cmp | Arith | In

# ---- rules


@dataclass(frozen=True, slots=True)
class When:
    """`when` implies `then`: the normal rule."""

    id: str
    when: Expr
    then: Expr
    source: str | None = None
    explain: str | None = None


@dataclass(frozen=True, slots=True)
class Define:
    """`var` holds exactly when `as_` holds (if and only if). Listed for review by the validator."""

    id: str
    var: str
    as_: Expr
    source: str | None = None
    explain: str | None = None


@dataclass(frozen=True, slots=True)
class Constraint:
    """A bare assertion. Allowed, but always reported by the validator."""

    id: str
    expr: Expr
    source: str | None = None
    explain: str | None = None


type Rule = When | Define | Constraint

# ---- variables, outcomes, policies


@dataclass(frozen=True, slots=True)
class System:
    """Comes from a system of record; never asked."""


@dataclass(frozen=True, slots=True)
class Ask:
    """Asked of the customer with `question`. A value they only mention in passing is confirmed first."""

    question: str
    confirm_volunteered: bool = True


@dataclass(frozen=True, slots=True)
class Derived:
    """Defined by the rules; never asked and never supplied."""


type Role = System | Ask | Derived


@dataclass(frozen=True, slots=True)
class Variable:
    name: str
    sort: Sort
    role: Role
    description: str
    phrasings: tuple[tuple[Lit, tuple[str, ...]], ...] = ()  # example wordings per value, for readers only


@dataclass(frozen=True, slots=True)
class Outcome:
    """A named result: the conjunction `var == value` over `assignment`. Outcomes are tried in policy order."""

    name: str
    assignment: tuple[tuple[str, Lit], ...]


@dataclass(frozen=True, slots=True)
class Policy:
    name: str
    version: str
    sorts: tuple[EnumSort, ...]
    variables: tuple[Variable, ...]
    rules: tuple[Rule, ...]
    outcomes: tuple[Outcome, ...]


CheckedPolicy = NewType("CheckedPolicy", Policy)
"""A `Policy` that `typecheck.check_policy` accepted. Every core function past decoding takes this type."""


def rule_id(rule: Rule) -> str:
    return rule.id
