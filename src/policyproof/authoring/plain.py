"""Facts and outcomes in plain words, for policy authors who don't read logic. Deterministic: no model involved."""
from __future__ import annotations

import re
from typing import Literal, assert_never

from policyproof.core.problems import Customer, Says
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
    """"Came by courier": the variable's display for this value; else its description (or its name as words) and the
    value."""
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
    return f"{(v.description or name_words(v.name)).rstrip('.')}: {_value(value)}"


def customer_phrases(p: CheckedPolicy, customer: Customer) -> tuple[str, ...]:
    variables = {v.name: v for v in p.variables}
    return tuple(phrase(variables[var], value) for var, value in customer if var in variables)


def name_words(name: str) -> str:
    """"Wants refund" for `wantsRefund`: for a name with nothing better to show."""
    words = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", name).replace("_", " ").split()
    text = " ".join(words).lower()
    return text[:1].upper() + text[1:]


def outcome_label(o: Outcome) -> str:
    """"A refund": the outcome's display; else its name split into words."""
    return o.display or name_words(o.name)


type Tone = Literal["yes", "no", "none"]


def verdict(p: CheckedPolicy, says: Says) -> tuple[str, Tone]:
    """What one rule says for a customer, in words: the outcome it forces ("A refund"); else the first outcome it
    rules out ("No refund", "Not a voucher"); else that it only can't hold with the others. An outcome made only of
    false flags reads as withholding something, so its tone is "no"."""
    forced = dict(says.forces)
    for o in p.outcomes:
        if o.assignment and all(forced.get(var) == x for var, x in o.assignment):
            return outcome_label(o), "no" if all(x == BoolLit(False) for _, x in o.assignment) else "yes"
    for o in p.outcomes:
        if any(var in forced and forced[var] != x for var, x in o.assignment):
            label = outcome_label(o)
            lower = label[:1].lower() + label[1:]
            return (f"Not {lower}" if re.match(r"(a|an|the) ", lower) else f"No {lower}"), "no"
    return "Can't hold together with the others", "none"
