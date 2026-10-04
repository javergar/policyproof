"""Reading a reader's plain value as a literal of a variable's sort, and finding a quote in a text."""
from fractions import Fraction

from returns.result import Failure, Result, Success

from policyproof.core.check import normalize
from policyproof.core.syntax import (
    BoolLit,
    BoolSort,
    EnumLit,
    EnumSort,
    IntLit,
    IntSort,
    Lit,
    Policy,
    RealLit,
    RealSort,
)
from policyproof.core.typecheck import sort_name


def literal_for(p: Policy, var: str, value: object) -> Result[Lit, str]:
    """`value` as a literal of `var`'s sort. Booleans may be `true`/`false` strings (as Jev's options are); enum
    values may be written `VALUE` or `Sort.VALUE`, in any case if that is unambiguous; reals are ints or
    `{"real": "2.5"}` (never floats, which are inexact)."""
    variable = next((v for v in p.variables if v.name == var), None)
    if variable is None:
        return Failure(f"unknown variable {var!r}")
    bad = Failure(f"{value!r} is not a {sort_name(variable.sort)} value for {var}")
    match variable.sort, value:
        case BoolSort(), bool():
            return Success(BoolLit(value))
        case BoolSort(), str() if value.lower() in ("true", "false"):
            return Success(BoolLit(value.lower() == "true"))
        case IntSort(), int() if not isinstance(value, bool):
            return Success(IntLit(value))
        case RealSort(), int() if not isinstance(value, bool):
            return Success(RealLit(Fraction(value)))
        case RealSort(), {"real": str() | int() as text} if len(value) == 1:
            try:
                return Success(RealLit(Fraction(text)))
            except ValueError:
                return bad
        case EnumSort(name, values), str():
            short = value.split(".", 1)[1] if value.lower().startswith(f"{name.lower()}.") else value
            same = [v for v in values if v == short] or [v for v in values if v.lower() == short.lower()]
            return Success(EnumLit(name, same[0])) if len(same) == 1 else bad
        case _:
            return bad


def in_text(quote: str, text: str) -> bool:
    """`quote` occurs in `text` as whole words, ignoring case and punctuation (the core's `normalize`)."""
    q = normalize(quote)
    return bool(q) and f" {q} " in f" {normalize(text)} "
