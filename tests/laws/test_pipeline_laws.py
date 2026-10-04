"""E4: guard_reply is total. Whatever the readers and the rewriter do, it returns, and what it sends either passed the
check or is the fallback."""
import asyncio

from conftest import load
from fakes import Claims, Rewriter
from hypothesis import event, given
from hypothesis import strategies as st
from returns.result import Failure, Success

from policyproof.core.decide import decide
from policyproof.core.facts import Answered, Fact, FromSystem, facts
from policyproof.core.solver import compile
from policyproof.core.syntax import BoolLit, IntLit
from policyproof.effects.errors import Malformed, Refused, Unavailable
from policyproof.effects.pipeline import guard_reply, template
from policyproof.effects.ports import RawClaim

C = compile(load("toy.yaml"))
FS = facts(Fact("daysLate", IntLit(3), FromSystem("t")), Fact("wantsRefund", BoolLit(True), Answered("q", "yes")))
DECISION = decide(C, FS)
TEXTS = st.sampled_from(["You'll get a refund.", "You'll get a voucher.", "Nothing."])
ERRORS = st.sampled_from([Unavailable("u"), Malformed("m"), Refused("r")]).map(Failure)
GOOD = Success((RawClaim("refund", "get a refund"),))
RAW = st.builds(RawClaim, st.sampled_from(["refund", "voucher", {"not": "refund"}, 3]),
                st.sampled_from(["get a refund", "get a voucher", "Nothing"]))
CLAIMS = st.one_of(ERRORS, st.just(GOOD), st.lists(RAW, max_size=3).map(lambda cs: Success(tuple(cs))))


@given(TEXTS, CLAIMS, CLAIMS, st.one_of(ERRORS, TEXTS.map(Success)))
def test_e4_guard_reply_is_total_and_never_sends_unchecked_text(draft, first, second, rewrite):
    g = asyncio.run(guard_reply(C, FS, DECISION, draft, Claims([first, second]), Rewriter(rewrite)))
    event("fell back" if g.fell_back else f"sent after {g.attempts}")
    if g.fell_back:
        assert g.text == template(DECISION) and g.reason
    else:
        assert g.result is not None and g.result.passed and g.reason is None
        assert g.text in (draft, rewrite.value_or(None))
