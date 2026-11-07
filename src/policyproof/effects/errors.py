"""Why a reader produced nothing. A guard rejecting what a reader produced is not an error (see `guards`)."""
from dataclasses import dataclass
from typing import Literal, assert_never


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


type Kind = Literal["failed", "refused", "unsupported"]


def kind(e: LLMError) -> Kind:
    """What an error says about the reading. 'failed': the reader didn't run properly (provider or output), so a
    configuration that hits it is broken. 'refused': the model was unsure or declined, an honest non-answer.
    'unsupported': the reader can't read this kind of value by design, so it had no say."""
    match e:
        case Unavailable() | Malformed():
            return "failed"
        case Refused():
            return "refused"
        case Unsupported():
            return "unsupported"
        case _:
            assert_never(e)


def worse(a: LLMError, b: LLMError) -> LLMError:
    """The error that speaks more strongly against a reading (failed, then refused, then unsupported); `a` on a tie."""
    order: list[Kind] = ["unsupported", "refused", "failed"]
    return b if order.index(kind(b)) > order.index(kind(a)) else a
