from policyproof.core.check import (
    DEFAULT_RULES,
    Claim,
    check_reply,
    forbid,
    only_entities,
    require_mention,
)
from policyproof.core.decide import decide
from policyproof.core.facts import Answered, Fact, FromSystem, facts
from policyproof.core.solver import compile
from policyproof.core.syntax import BoolLit, IntLit, Not, Var

LATE = Fact("daysLate", IntLit(3), FromSystem("tracking"))
WANTS = Fact("wantsRefund", BoolLit(True), Answered("Would you like your money back?", "yes"))
REFUND = Claim(Var("refund"), "you will get a full refund")


def setup(toy, *fs):
    c = compile(toy)
    known = facts(*fs)
    return c, decide(c, known), known


def test_a_proven_reply_passes(toy):
    c, d, fs = setup(toy, LATE, WANTS)
    reply = "Our tracking shows the parcel was 3 days late, so you will get a full refund."
    result = check_reply(c, d, fs, reply, [REFUND])
    assert result.passed and [r.status for r in result.claims] == ["proven"]


def test_extra_promises_are_caught(toy):
    c, d, fs = setup(toy, LATE, WANTS)
    reply = "You will get a full refund and a voucher."
    result = check_reply(c, d, fs, reply, [REFUND, Claim(Var("voucher"), "and a voucher")])
    assert not result.passed and [r.status for r in result.claims] == ["proven", "contradicts"]


def test_claims_before_the_decision_are_not_proven(toy):
    c, d, fs = setup(toy, LATE)
    reply = "You will get a full refund. Would you like your money back?"
    result = check_reply(c, d, fs, reply, [REFUND])
    assert [r.status for r in result.claims] == ["not_proven"]
    assert [p.rule for p in result.problems] == ["claims_hold"]


def test_ungrounded_claims_are_reported_but_not_held_against_the_reply(toy):
    c, d, fs = setup(toy, LATE, WANTS)
    reply = "Good news: you will get a full refund."
    result = check_reply(c, d, fs, reply, [REFUND, Claim(Not(Var("voucher")), "no voucher")])
    assert result.passed and result.claims[1].status == "ungrounded"


def test_a_decided_reply_must_state_the_outcome(toy):
    c, d, fs = setup(toy, LATE, WANTS)
    result = check_reply(c, d, fs, "Thanks for waiting.", [])
    assert [p.rule for p in result.problems] == ["states_outcome"]


def test_the_open_question_is_asked_verbatim_last_and_alone(toy):
    c, d, fs = setup(toy, LATE)
    ok = check_reply(c, d, fs, "Your parcel was late. Would you like your money back?", [])
    reworded = check_reply(c, d, fs, "Do you want a refund?", [])
    not_last = check_reply(c, d, fs, "Would you like your money back? Or a voucher instead.", [])
    either_or = check_reply(c, d, fs, "Would you like a voucher, or would you like your money back?", [])
    assert ok.passed
    assert [p.rule for p in reworded.problems] == ["asks_open_question"]
    assert [p.rule for p in not_last.problems] == ["asks_open_question"]
    assert [p.rule for p in either_or.problems] == ["single_question"]


def test_domain_rules(toy):
    c, d, fs = setup(toy, LATE, WANTS)
    rules = (*DEFAULT_RULES, forbid(r"\$\s?\d+|compensation", "Offers the policy doesn't make"),
             require_mention(r"tracking", "Say where the facts came from"),
             only_entities(r"\bPX\d{3}\b", frozenset({"PX123"}), "Unknown parcels"))
    reply = "You will get a full refund plus $20 compensation for PX999."
    result = check_reply(c, d, fs, reply, [REFUND], rules)
    assert [p.rule for p in result.problems] == ["forbid", "require_mention", "only_entities"]
    assert result.problems[0].message.endswith("$20, compensation")
