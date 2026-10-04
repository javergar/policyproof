"""Checking claims a reader found in a reply, before the core judges them.

A claim is kept only if its expression decodes against the policy, is a true/false statement, mentions at least one
policy variable (a bare `true` claims nothing), and its quote is in the reply.
"""
from collections.abc import Sequence

from returns.result import Failure, Result, Success

from policyproof.core._result import unreachable
from policyproof.core.check import Claim
from policyproof.core.codec import decode_expr, from_data
from policyproof.core.semantics import free_vars
from policyproof.core.syntax import BOOL, Expr, Policy
from policyproof.core.typecheck import Signature, signature, sort_of
from policyproof.guards.raw import RawClaim, Rejected
from policyproof.guards.values import in_text


def _expr(sig: Signature, data: object) -> Result[Expr, str]:
    match from_data(data).bind(lambda t: decode_expr(sig, t, "expr")):
        case Success(e):
            if sort_of(sig, e) != Success(BOOL):
                return Failure("not a true/false statement")
            if not free_vars(e):
                return Failure("mentions no policy variable")
            return Success(e)
        case Failure(err):
            return Failure(f"{err.path}: {err.message}")
        case _:
            unreachable()


def check(p: Policy, reply: str, raws: Sequence[RawClaim]) -> tuple[tuple[Claim, ...], tuple[Rejected, ...]]:
    sig = signature(p)
    kept: list[Claim] = []
    rejected: list[Rejected] = []
    for raw in raws:
        result = _expr(sig, raw.expr) if in_text(raw.quote, reply) else Failure("quote not in reply")
        match result:
            case Success(e):
                kept.append(Claim(e, raw.quote))
            case Failure(reason):
                rejected.append(Rejected(raw.quote, reason))
            case _:
                unreachable()
    return tuple(kept), tuple(rejected)
