"""The instructions each LLM reader sends, built from the policy. Pure functions, so they are tested as snapshots."""
from collections.abc import Iterable
from typing import assert_never

from policyproof.core.check import Problem
from policyproof.core.syntax import (
    Ask,
    BoolLit,
    BoolSort,
    Derived,
    EnumLit,
    EnumSort,
    IntLit,
    IntSort,
    Lit,
    Policy,
    RealLit,
    RealSort,
    Sort,
    Variable,
)


def values_of(s: Sort) -> str:
    match s:
        case BoolSort():
            return "true or false"
        case IntSort():
            return "a whole number"
        case RealSort():
            return 'a number, written {"real": "2.5"}'
        case EnumSort(_, values):
            return "one of " + ", ".join(values)
        case _:
            assert_never(s)


def value_text(lit: Lit) -> str:
    match lit:
        case BoolLit(b):
            return "true" if b else "false"
        case IntLit(n):
            return str(n)
        case RealLit(q):
            return str(q)
        case EnumLit(_, value):
            return value
        case _:
            assert_never(lit)


def said_as(v: Variable) -> str:
    """The variable's phrasings as one line (`said as: true: "money back"; false: ...`), or "" without any."""
    if not v.phrasings:
        return ""
    return "said as: " + "; ".join(f"{value_text(lit)}: " + ", ".join(f'"{t}"' for t in texts)
                                   for lit, texts in v.phrasings)


def describe(vs: Iterable[Variable], *, phrasings: bool = False) -> str:
    def line(v: Variable) -> str:
        head = f"- {v.name} ({values_of(v.sort)}): {v.description}"
        return f"{head}\n  {said_as(v)}" if phrasings and v.phrasings else head
    return "\n".join(line(v) for v in vs)


def examples(p: Policy) -> str:
    """Example expressions using the policy's own names: one per kind of variable the policy has."""
    found: list[str] = []
    for v in p.variables:
        match v.sort:
            case BoolSort() if not any(e.startswith('"') for e in found):
                found += [f'"{v.name}"', f'{{"not": "{v.name}"}}']
            case EnumSort(_, values) if not any('"eq"' in e for e in found):
                found.append(f'{{"eq": ["{v.name}", "{values[0]}"]}}')
            case IntSort() if not any('"ge"' in e for e in found):
                found.append(f'{{"ge": ["{v.name}", 2]}}')
            case RealSort() if not any('"ge"' in e for e in found):
                found.append(f'{{"ge": ["{v.name}", {{"real": "2.5"}}]}}')
            case _:
                pass
    return ", ".join(found)


def answer_prompt(p: Policy, var: str) -> str:
    v = next(x for x in p.variables if x.name == var)
    assert isinstance(v.role, Ask)
    said = f"\n{said_as(v)}" if v.phrasings else ""
    return f"""You read a customer's reply to one question and decide whether it answers it.

QUESTION ASKED: {v.role.question}
WHAT IT DECIDES: {v.name} ({values_of(v.sort)}): {v.description}{said}

Report:
- status "answered" when the reply gives one clear answer: set value, and quote the reply's exact words that give it.
- status "unclear" when the reply tries to answer but is hedged, ambiguous or contradicts itself: give a reason.
- status "not_answered" when the reply doesn't answer the question (for example, it asks something else).
Never guess. Quote word for word."""


def facts_prompt(p: Policy) -> str:
    asked = [v for v in p.variables if not isinstance(v.role, Derived)]
    return f"""You find facts a customer states in a message, for these variables only:
{describe(asked, phrasings=True)}

Report a fact only when the message states it; don't infer one from tone or context. For each fact, quote the
message's exact words that state it. Report nothing for a variable the message doesn't mention."""


def claims_prompt(p: Policy) -> str:
    enums = "\n".join(f"- {s.name}: {', '.join(s.values)}" for s in p.sorts) or "- (none)"
    return f"""You list every checkable statement a support reply makes about these policy variables:
{describe(p.variables)}

Enum values:
{enums}

Write each statement as an expression: a variable name; a value (true, false, a whole number, an enum value, or
{{"real": "2.5"}}); or a one-key operator map. Operators: not, and, or, implies, iff (on true/false statements); eq, ne,
lt, le, gt, ge (comparisons of two operands); add, sub, mul (arithmetic); in ([operand, [values]]).
Examples: {examples(p)}.

Quote the reply's exact words for each statement. Leave out statements that mention no variable, and greetings,
apologies and questions."""


def rewrite_prompt(problems: tuple[Problem, ...], instructions: str) -> str:
    listed = "\n".join(f"- {pr.message}" for pr in problems)
    extra = f"\n\nAlso follow these instructions:\n{instructions}" if instructions else ""
    return f"""You rewrite a support reply so that it fixes every problem below and changes nothing else. Don't add
claims, offers or promises. Return only the new reply.

Problems:
{listed}{extra}"""
