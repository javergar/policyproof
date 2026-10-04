"""Checking facts a reader found in a message (things the customer said without being asked).

A fact is kept only if its variable exists and isn't derived, its value has the variable's sort, and its evidence
holds: a quote must be in the message, a confidence must reach the bar. Kept facts are merged with the core's
`merge`, so two kept facts that conflict both stay, and `decide` reports the contradiction.
"""
from collections.abc import Sequence
from typing import assert_never

from returns.result import Failure, Result, Success

from policyproof.core._result import unreachable
from policyproof.core.facts import Fact, Facts, Quoted, Scored, Volunteered, facts
from policyproof.core.syntax import Derived, Policy
from policyproof.guards.raw import RawFact, Rejected
from policyproof.guards.values import in_text, literal_for


def _fact(p: Policy, message: str, raw: RawFact, min_confidence: float) -> Result[Fact, str]:
    variable = next((v for v in p.variables if v.name == raw.var), None)
    if variable is not None and isinstance(variable.role, Derived):
        return Failure(f"{raw.var} is derived by the rules; it can't be given as a fact")
    match raw.evidence:
        case Quoted(text) if not in_text(text, message):
            return Failure("quote not in message")
        case Scored(confidence) if confidence < min_confidence:
            return Failure(f"confidence {confidence:g} is below {min_confidence:g}")
        case Quoted() | Scored():
            return literal_for(p, raw.var, raw.value).map(lambda lit: Fact(raw.var, lit, Volunteered(raw.evidence)))
        case _:
            assert_never(raw.evidence)


def check(p: Policy, message: str, raws: Sequence[RawFact], *, min_confidence: float = 0.5
          ) -> tuple[Facts, tuple[Rejected, ...]]:
    kept: list[Fact] = []
    rejected: list[Rejected] = []
    for raw in raws:
        match _fact(p, message, raw, min_confidence):
            case Success(f):
                kept.append(f)
            case Failure(reason):
                rejected.append(Rejected(raw.var, reason))
            case _:
                unreachable()
    return facts(*kept), tuple(rejected)
