"""Small helpers over `returns.result.Result` that need no higher-kinded types."""
from collections.abc import Iterable
from typing import NoReturn

from returns.pipeline import is_successful
from returns.result import Failure, Result, Success


def unreachable() -> NoReturn:
    """The last case of a `match` on a `Result`: checkers can't prove `Success | Failure` exhaustive."""
    raise AssertionError("unreachable")


def sequence[T, E](results: Iterable[Result[T, E]]) -> Result[tuple[T, ...], E]:
    """All successes as a tuple, or the first failure. Stops at the first failure."""
    values: list[T] = []
    for r in results:
        if not is_successful(r):
            return Failure(r.failure())
        values.append(r.unwrap())
    return Success(tuple(values))


def errors[T, E](r: Result[T, E]) -> tuple[E, ...]:
    """() for a success, (error,) for a failure: for collecting every error instead of the first."""
    return () if is_successful(r) else (r.failure(),)
