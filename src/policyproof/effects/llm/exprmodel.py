"""The policy format's expression grammar as recursive pydantic models: the schema an LLM fills to report claims.

pydantic-ai can't take our published JSON Schema as an output type (its `StructuredDict` refuses recursive `$defs`),
so the grammar is mirrored here. Law E1 keeps the two in step; `codec.decode_expr` is still what reads the result.
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class _Op(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, validate_by_name=True, serialize_by_alias=True)


class Real(_Op):
    """An exact number, e.g. {"real": "2.5"} or {"real": "1/3"}."""
    real: str | int


class Not(_Op):
    not_: Expr = Field(alias="not")


class And(_Op):
    and_: list[Expr] = Field(alias="and", min_length=2)


class Or(_Op):
    or_: list[Expr] = Field(alias="or", min_length=2)


class Implies(_Op):
    implies: list[Expr] = Field(min_length=2, max_length=2)


class Iff(_Op):
    iff: list[Expr] = Field(min_length=2, max_length=2)


class Eq(_Op):
    eq: list[Expr] = Field(min_length=2, max_length=2)


class Ne(_Op):
    ne: list[Expr] = Field(min_length=2, max_length=2)


class Lt(_Op):
    lt: list[Expr] = Field(min_length=2, max_length=2)


class Le(_Op):
    le: list[Expr] = Field(min_length=2, max_length=2)


class Gt(_Op):
    gt: list[Expr] = Field(min_length=2, max_length=2)


class Ge(_Op):
    ge: list[Expr] = Field(min_length=2, max_length=2)


class Add(_Op):
    add: list[Expr] = Field(min_length=2)


class Sub(_Op):
    sub: list[Expr] = Field(min_length=2, max_length=2)


class Mul(_Op):
    mul: list[Expr] = Field(min_length=2)


class In(_Op):
    """Membership: {"in": [expr, [value, ...]]}."""
    in_: tuple[Expr, list[bool | int | str | Real]] = Field(alias="in")


type Expr = (bool | int | str | Real | Not | And | Or | Implies | Iff | Eq | Ne | Lt | Le | Gt | Ge | Add | Sub | Mul
             | In)


class Claim(_Op):
    """One checkable statement the reply makes."""
    expr: Expr = Field(description="The statement, as an expression over the policy's variables.")
    quote: str = Field(description="The exact words of the reply that make this statement.")


class Claims(_Op):
    """Every checkable statement the reply makes about the policy's variables."""
    claims: list[Claim]
