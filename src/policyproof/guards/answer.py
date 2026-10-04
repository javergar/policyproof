"""Checking a reader's answer to the question the customer was asked.

The answer becomes a fact only if its quote is in the message, its value has the variable's sort, and, for a yes/no
question, it doesn't contradict a plain "yes" or "no" the message opens with ("Yes, please cancel it" read as false
is unclear, not false). Everything else is `Unclear`, so the question is asked again.
"""
import re
from dataclasses import dataclass
from typing import assert_never

from returns.result import Failure, Success

from policyproof.core._result import unreachable
from policyproof.core.facts import Answered, Fact
from policyproof.core.syntax import Ask, BoolLit, BoolSort, Policy
from policyproof.guards.raw import NotAnswered, RawAnswer, Said, Unclear
from policyproof.guards.values import in_text, literal_for

YES = r"(yes|yeah|yep|yup|sure|correct|that's right|that is right)"
NO = r"(no|nope|nah|not really)"


@dataclass(frozen=True, slots=True)
class Answer:
    fact: Fact


type Reading = Answer | Unclear | NotAnswered


def opening_word(message: str) -> bool | None:
    """True or False if the message opens with a plain yes or no word, else None."""
    text = message.strip().lower()
    if re.match(rf"{YES}\b", text):
        return True
    if re.match(rf"{NO}\b", text):
        return False
    return None


def check(p: Policy, var: str, message: str, raw: RawAnswer) -> Reading:
    variable = next((v for v in p.variables if v.name == var), None)
    if variable is None or not isinstance(variable.role, Ask):
        return Unclear("not an askable variable")
    match raw:
        case Said(value, quote):
            if not in_text(quote, message):
                return Unclear("quote not in message")
            match literal_for(p, var, value):
                case Failure(reason):
                    return Unclear(reason)
                case Success(lit):
                    lead = opening_word(message)
                    if isinstance(variable.sort, BoolSort) and lead is not None and BoolLit(lead) != lit:
                        return Unclear("opening contradicts answer")
                    return Answer(Fact(var, lit, Answered(variable.role.question, quote)))
                case _:
                    unreachable()
        case Unclear() | NotAnswered():
            return raw
        case _:
            assert_never(raw)
