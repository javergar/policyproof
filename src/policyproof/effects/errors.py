"""Why a reader produced nothing. A guard rejecting what a reader produced is not an error (see `guards`)."""
from dataclasses import dataclass
from typing import assert_never


@dataclass(frozen=True, slots=True)
class Unavailable:
    """The provider couldn't be reached or refused the request: network, throttling, authentication, 5xx."""
    message: str


@dataclass(frozen=True, slots=True)
class Malformed:
    """The model's output never passed validation, even after the allowed retries."""
    message: str


@dataclass(frozen=True, slots=True)
class Refused:
    """The model declined, a content filter fired, or Jev handed the step off as too uncertain."""
    message: str


@dataclass(frozen=True, slots=True)
class Unsupported:
    """The reader can't read this kind of value at all (e.g. Jev and number answers): it has no reading, so another
    reader's stands."""
    message: str


type LLMError = Unavailable | Malformed | Refused | Unsupported


def describe(e: LLMError) -> str:
    match e:
        case Unavailable(m):
            return f"provider unavailable: {m}"
        case Malformed(m):
            return f"unusable output: {m}"
        case Refused(m):
            return f"refused: {m}"
        case Unsupported(m):
            return f"unsupported: {m}"
        case _:
            assert_never(e)
