"""What readers return, before any guard has looked at it: plain values, unverified quotes, untyped expressions."""
from dataclasses import dataclass

from policyproof.core.facts import Evidence


@dataclass(frozen=True, slots=True)
class Said:
    """The message answers the question with `value`, in the words `quote`."""
    value: object
    quote: str


@dataclass(frozen=True, slots=True)
class Unclear:
    """The message tries to answer but can't be read as one value; the question is asked again."""
    reason: str


@dataclass(frozen=True, slots=True)
class NotAnswered:
    """The message doesn't answer the question (e.g. it asks something else)."""


type RawAnswer = Said | Unclear | NotAnswered


@dataclass(frozen=True, slots=True)
class RawFact:
    var: str
    value: object
    evidence: Evidence


@dataclass(frozen=True, slots=True)
class RawClaim:
    expr: object  # plain data in the policy format's expression shape
    quote: str


@dataclass(frozen=True, slots=True)
class Rejected:
    """Something a guard dropped: the variable name or the claim's quote, and why."""
    item: str
    reason: str
