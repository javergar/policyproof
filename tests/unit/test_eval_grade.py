import pytest

from policyproof.core.decide import Contradiction, Decided, Escalate, InvalidFacts, NeedInfo
from policyproof.core.facts import Answered, Fact, FromSystem, Quoted, Volunteered, facts
from policyproof.core.syntax import BoolLit, IntLit
from policyproof.eval.cases import AskExpected, EscalateExpected, OutcomeExpected, ReplyCase, TurnCase
from policyproof.eval.grade import (
    Conservative,
    Correct,
    Crashed,
    ReaderFailed,
    ReplySeen,
    TurnSeen,
    Wrong,
    grade_reply,
    grade_turn,
    worst,
)

REFUND = Decided("refund", ("T2",), ())
VOUCHER = Decided("voucher", ("T3",), ())
ASK = NeedInfo("wantsRefund", "q", "missing", ())
ASK_OTHER = NeedInfo("carrier", "q", "missing", ())


def turn(expect, want=()):
    return TurnCase("c", False, {}, None, "m", expect, want)


@pytest.mark.parametrize(("expect", "decision", "grade"), [
    (OutcomeExpected("refund"), REFUND, Correct()),
    (OutcomeExpected("refund"), VOUCHER, Wrong("decided voucher, expected refund")),
    (OutcomeExpected("refund"), ASK, Conservative("asked about wantsRefund instead of deciding refund")),
    (OutcomeExpected("refund"), Escalate("x"), Conservative("escalated (x) instead of deciding refund")),
    (OutcomeExpected("refund"), Contradiction(("T1",), ()),
     Conservative("found a contradiction instead of deciding refund")),
    (AskExpected("wantsRefund"), ASK, Correct()),
    (AskExpected("wantsRefund"), ASK_OTHER, Conservative("asked about carrier, expected wantsRefund")),
    (AskExpected("wantsRefund"), Escalate("x"), Conservative("escalated (x) instead of asking about wantsRefund")),
    (AskExpected("wantsRefund"), REFUND, Wrong("decided refund, expected a question about wantsRefund")),
    (EscalateExpected(), Escalate("x"), Correct()),
    (EscalateExpected(), Contradiction(("T1",), ()), Correct()),
    (EscalateExpected(), REFUND, Wrong("decided refund, expected an escalation")),
    (EscalateExpected(), ASK, Conservative("asked about wantsRefund instead of escalating")),
    (OutcomeExpected("refund"), InvalidFacts(("bad",)), Wrong("invalid facts reached the decision: bad")),
])
def test_turn_grading_table(expect, decision, grade):
    assert grade_turn(turn(expect), TurnSeen(decision, {})) == grade


def test_reader_failures_are_conservative_and_crashes_wrong():
    assert grade_turn(turn(OutcomeExpected("refund")), ReaderFailed("provider unavailable: down")) == Conservative(
        "reader error: provider unavailable: down")
    assert grade_turn(turn(OutcomeExpected("refund")), Crashed("KeyError: 'x'")) == Wrong("crashed: KeyError: 'x'")
    assert grade_reply(ReplyCase("c", False, {}, "d", "pass"), Crashed("boom")) == Wrong("crashed: boom")


def test_expected_facts_must_be_read_with_their_values():
    want = (("wantsRefund", BoolLit(True)),)
    said = Fact("wantsRefund", BoolLit(True), Answered("q", "yes"))
    misread = Fact("wantsRefund", BoolLit(False), Volunteered(Quoted("no")))
    late = Fact("daysLate", IntLit(3), FromSystem("t"))
    case = turn(OutcomeExpected("refund"), want)
    assert grade_turn(case, TurnSeen(REFUND, facts(late, said))) == Correct()
    assert grade_turn(case, TurnSeen(REFUND, facts(late))) == Conservative("wantsRefund was not read")
    assert grade_turn(case, TurnSeen(REFUND, facts(late, misread))) == Wrong(
        "misread wantsRefund: read false, expected true")
    assert grade_turn(case, TurnSeen(ASK, facts(late, misread))) == Wrong(
        "misread wantsRefund: read false, expected true")  # the worse of decision and facts


@pytest.mark.parametrize(("expect", "as_written", "grade"), [
    ("caught", False, Correct()),
    ("caught", True, Wrong("the draft was sent as written, expected it to be caught")),
    ("pass", True, Correct()),
    ("pass", False, Conservative("a good draft was rewritten or replaced")),
])
def test_reply_grading_table(expect, as_written, grade):
    assert grade_reply(ReplyCase("c", False, {}, "d", expect), ReplySeen(as_written)) == grade


def test_a_case_is_as_bad_as_its_worst_run():
    assert worst([Correct(), Conservative("a"), Wrong("b"), Conservative("c")]) == Wrong("b")
    assert worst([Correct(), Conservative("a"), Conservative("c")]) == Conservative("a")
    assert worst([Correct(), Correct()]) == Correct()
    assert worst([]) == Correct()
