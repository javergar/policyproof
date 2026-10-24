"""Facts and outcomes in plain words, for policy authors who don't read logic. Deterministic: no model involved."""
from __future__ import annotations

import re
from typing import assert_never

from policyproof.core.problems import Customer
from policyproof.core.syntax import (
    BoolLit,
    CheckedPolicy,
    EnumLit,
    IntLit,
    Lit,
    Outcome,
    RealLit,
    Template,
    ValuePhrases,
    Variable,
)


def _value(lit: Lit) -> str:
    match lit:
        case BoolLit(b):
            return "yes" if b else "no"
        case IntLit(n):
            return str(n)
        case RealLit(q):
            return str(q.numerator) if q.denominator == 1 else f"{float(q):g}"
        case EnumLit(_, value):
            return value
        case _:
            assert_never(lit)


def phrase(v: Variable, value: Lit) -> str:
    """"Came by courier": the variable's display for this value; else its description and the value."""
    match v.display:
        case ValuePhrases(phrases):
            shown = next((text for lit, text in phrases if lit == value), None)
            if shown is not None:
                return shown
        case Template(text):
            return text.replace("{}", _value(value), 1)
        case None:
            pass
        case _:
            assert_never(v.display)
    return f"{(v.description or v.name).rstrip('.')}: {_value(value)}"


def customer_phrases(p: CheckedPolicy, customer: Customer) -> tuple[str, ...]:
    variables = {v.name: v for v in p.variables}
    return tuple(phrase(variables[var], value) for var, value in customer if var in variables)


def outcome_label(o: Outcome) -> str:
    """"A refund": the outcome's display; else its name split into words."""
    if o.display:
        return o.display
    words = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", o.name).replace("_", " ").split()
    text = " ".join(words).lower()
    return text[:1].upper() + text[1:]
