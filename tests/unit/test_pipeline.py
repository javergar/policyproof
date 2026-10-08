import asyncio

import pytest
from conftest import POLICIES
from fakes import Answers, Claims, Facts, Rewriter
from returns.result import Failure, Success

from policyproof.core.codec import from_yaml
from policyproof.core.decide import Decided, Escalate, NeedInfo, decide
from policyproof.core.facts import Answered, Fact, FromSystem, Quoted, facts
from policyproof.core.solver import compile
from policyproof.core.syntax import BoolLit, IntLit
from policyproof.effects.errors import Malformed, Unavailable
from policyproof.effects.pipeline import Conversation, Readers, guard_reply, read_turn, template
from policyproof.effects.ports import NotAnswered, RawClaim, RawFact, Rejected, Said, Unclear
from policyproof.guards.answer import Answer

Q = "Would you like your money back?"
LATE = Fact("daysLate", IntLit(3), FromSystem("tracking"))
NO_FACTS = Facts(Success(()))


@pytest.fixture(scope="module")
def c(toy):
    return compile(toy)


@pytest.fixture(scope="module")
def asked(c):
    pending = decide(c, facts(LATE))
    assert isinstance(pending, NeedInfo) and pending.var == "wantsRefund"
    return Conversation(facts(LATE), pending, frozenset())


def turn(c, state, message, answers, found=NO_FACTS):
    return asyncio.run(read_turn(c, state, message, Readers(answers, found)))


def test_an_answer_to_the_pending_question_decides(c, asked):
    got = turn(c, asked, "Yes, money back please", Answers(Success(Said(True, "money back"))))
    t = got.unwrap()
    assert isinstance(t.decision, Decided) and t.decision.outcome == "refund"
    assert t.answer == Answer(Fact("wantsRefund", BoolLit(True), Answered(Q, "money back")))
    assert t.state.pending is None and t.state.unclear == frozenset()
    assert t.rejected == () and t.degraded == ()


def test_an_unclear_answer_asks_again(c, asked):
    t = turn(c, asked, "Yes, a voucher", Answers(Success(Said(False, "a voucher")))).unwrap()
    assert t.answer == Unclear("opening contradicts answer")
    assert isinstance(t.decision, NeedInfo) and t.decision.reason == "unclear"
    assert t.state.unclear == frozenset({"wantsRefund"}) and t.state.pending == t.decision


def test_a_clear_answer_clears_unclear(c, asked):
    again = Conversation(asked.facts, asked.pending, frozenset({"wantsRefund"}))
    t = turn(c, again, "money back", Answers(Success(Said(True, "money back")))).unwrap()
    assert t.state.unclear == frozenset()


def test_not_answering_keeps_the_question_open(c, asked):
    t = turn(c, asked, "When is the next parcel?", Answers(Success(NotAnswered()))).unwrap()
    assert t.answer == NotAnswered()
    assert isinstance(t.decision, NeedInfo) and t.decision.var == "wantsRefund" and t.decision.reason == "missing"


def test_without_a_pending_question_no_answer_is_read(c):
    answers = Answers(Success(Said(True, "x")))
    t = turn(c, Conversation(facts(LATE), None, frozenset()), "hello", answers).unwrap()
    assert answers.asked == [] and t.answer is None


def test_the_turn_fails_if_the_answer_cannot_be_read(c, asked):
    assert turn(c, asked, "Yes", Answers(Failure(Unavailable("down")))) == Failure(Unavailable("down"))


def test_the_turn_goes_on_without_volunteered_facts_if_they_cannot_be_read(c, asked):
    t = turn(c, asked, "Yes, money back", Answers(Success(Said(True, "money back"))), Facts(Failure(Malformed("x"))))
    t = t.unwrap()
    assert t.degraded == (Malformed("x"),) and isinstance(t.decision, Decided)


def test_volunteered_facts_are_guarded_and_merged(c, asked):
    found = Facts(Success((RawFact("carrier", "COURIER", Quoted("by courier")),
                           RawFact("refund", True, Quoted("money back")))))
    t = turn(c, asked, "It came by courier, money back please", Answers(Success(Said(True, "money back"))), found)
    t = t.unwrap()
    assert "carrier" in t.state.facts
    assert t.rejected == (Rejected("refund", "refund is derived by the rules; it can't be given as a fact"),)


# ---- guard_reply

ANSWERED = facts(LATE, Fact("wantsRefund", BoolLit(True), Answered(Q, "yes")))
GOOD = "You'll get a refund."
BAD = "You'll get a voucher."
GOOD_CLAIMS = Success((RawClaim("refund", "get a refund"),))
BAD_CLAIMS = Success((RawClaim("voucher", "get a voucher"),))


def guard(c, draft, claims, rewriter):
    d = decide(c, ANSWERED)
    return asyncio.run(guard_reply(c, ANSWERED, d, draft, claims, rewriter))


def test_a_reply_that_passes_is_sent_as_written(c):
    g = guard(c, GOOD, Claims([GOOD_CLAIMS]), Rewriter(Success("unused")))
    assert (g.text, g.attempts, g.fell_back, g.reason) == (GOOD, 1, False, None)
    assert g.result is not None and g.result.passed


def test_a_failing_reply_is_rewritten_once_and_checked_again(c):
    rewriter = Rewriter(Success(GOOD))
    g = guard(c, BAD, Claims([BAD_CLAIMS, GOOD_CLAIMS]), rewriter)
    assert (g.text, g.attempts, g.fell_back) == (GOOD, 2, False)
    assert [p.rule for p in rewriter.problems[0]] == ["claims_hold", "states_outcome"]


def test_a_reply_that_fails_twice_falls_back(c):
    g = guard(c, BAD, Claims([BAD_CLAIMS]), Rewriter(Success(BAD)))
    assert g.text == template(decide(c, ANSWERED)) == "Under the policy, the outcome is refund."
    assert g.fell_back and g.attempts == 2 and g.reason == "the reply failed the check twice"


def test_unreadable_claims_fall_back(c):
    g = guard(c, GOOD, Claims([Failure(Unavailable("down"))]), Rewriter(Success(GOOD)))
    assert g.fell_back and g.result is None and g.reason == "provider unavailable: down"


def test_a_failed_rewrite_falls_back(c):
    g = guard(c, BAD, Claims([BAD_CLAIMS]), Rewriter(Failure(Malformed("x"))))
    assert g.fell_back and g.attempts == 1 and g.reason == "unusable output: x"


def test_claims_the_guard_rejects_fail_the_check(c):
    sneaky = Success((RawClaim("refund", "get a refund"), RawClaim("voucher", "a voucher too")))
    g = guard(c, GOOD, Claims([sneaky]), Rewriter(Success(BAD)))
    assert g.fell_back
    rewriter = Rewriter(Success(GOOD))
    guard(c, GOOD, Claims([sneaky, GOOD_CLAIMS]), rewriter)
    assert rewriter.problems[0][-1].rule == "claims_readable"


def test_the_answer_reader_decides_the_asked_variable_not_a_volunteered_fact(toy):
    """An answer the guard found unclear can't decide the turn through a volunteered fact about the same variable."""
    question = "question: Would you like your money back?"
    text = (POLICIES / "toy.yaml").read_text().replace(question, f"{question}\n    confirm_volunteered: false")
    trusting = compile(from_yaml(text).unwrap())
    pending = decide(trusting, facts(LATE))
    assert isinstance(pending, NeedInfo)
    found = Facts(Success((RawFact("wantsRefund", False, Quoted("a voucher is fine")),)))
    t = turn(trusting, Conversation(facts(LATE), pending, frozenset()), "Yes, a voucher is fine.",
             Answers(Success(Said(False, "a voucher is fine"))), found).unwrap()
    assert t.answer == Unclear("opening contradicts answer")
    assert isinstance(t.decision, NeedInfo) and t.decision.var == "wantsRefund" and t.decision.reason == "unclear"
    assert "wantsRefund" not in t.state.facts
    assert [r.item for r in t.rejected] == ["wantsRefund"]


def test_an_empty_rewrite_falls_back_even_when_nothing_is_required(c):
    """An escalation requires nothing of the reply, so an empty rewrite would pass the check vacuously."""
    g = asyncio.run(guard_reply(c, ANSWERED, Escalate("review"), BAD, Claims([BAD_CLAIMS, Success(())]),
                                Rewriter(Success("  "))))
    assert g.fell_back and g.reason == "the rewrite was empty" and g.text == "A person will review this."
