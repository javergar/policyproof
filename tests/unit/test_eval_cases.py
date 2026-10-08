import pytest
from conftest import POLICIES
from returns.result import Failure, Success

from policyproof.core.facts import Answered, Fact, FromSystem, facts
from policyproof.core.syntax import BoolLit, IntLit
from policyproof.eval.cases import (
    AskExpected,
    CaseError,
    EscalateExpected,
    OutcomeExpected,
    ReplyCase,
    TurnCase,
    decode,
    load,
)

Q = "Would you like your money back?"
TOY = str(POLICIES / "toy.yaml")
TURN = {"id": "plain-yes", "turn": {"facts": {"daysLate": 3}, "asked": "wantsRefund",
                                    "message": "Yes please, money back."},
        "expect": {"decision": "refund", "facts": {"wantsRefund": True}}}
REPLY = {"id": "voucher-caught", "held_out": True,
         "reply": {"facts": {"daysLate": 3, "wantsRefund": True}, "draft": "You'll get a voucher."},
         "expect": "caught"}


def file(*cases: dict) -> dict:
    return {"policy": TOY, "cases": list(cases)}


def test_a_turn_case_decodes_with_given_facts_and_expectations():
    f = decode(file(TURN), POLICIES).unwrap()
    assert f.cases == (TurnCase("plain-yes", False, facts(Fact("daysLate", IntLit(3), FromSystem("case"))),
                                "wantsRefund", "Yes please, money back.", OutcomeExpected("refund"),
                                (("wantsRefund", BoolLit(True)),)),)
    assert f.policy.name == "toy-delivery"


def test_a_reply_case_marks_askable_facts_as_answered():
    case = decode(file(REPLY), POLICIES).unwrap().cases[0]
    assert case == ReplyCase("voucher-caught", True, facts(Fact("daysLate", IntLit(3), FromSystem("case")),
                                                           Fact("wantsRefund", BoolLit(True), Answered(Q, "case"))),
                             "You'll get a voucher.", "caught")


def test_ask_and_escalate_expectations():
    ask = {**TURN, "expect": {"decision": {"ask": "wantsRefund"}}}
    esc = {**TURN, "id": "esc", "expect": {"decision": "escalate"}}
    got = decode(file(ask, esc), POLICIES).unwrap().cases
    assert [c.expect for c in got] == [AskExpected("wantsRefund"), EscalateExpected()]


def test_load_reads_the_policy_relative_to_the_case_file(tmp_path):
    (tmp_path / "toy.yaml").write_text((POLICIES / "toy.yaml").read_text())
    (tmp_path / "cases.yaml").write_text("policy: toy.yaml\ncases:\n  - id: a\n    turn: {message: hi}\n"
                                         "    expect: {decision: {ask: wantsRefund}}\n")
    f = load(tmp_path / "cases.yaml").unwrap()
    assert f.cases[0].id == "a" and f.source == str(tmp_path / "toy.yaml")


@pytest.mark.parametrize(("case", "path", "message"), [
    ({**TURN, "turn": {**TURN["turn"], "facts": {"daysLate": "three"}}}, "cases[0].turn.facts.daysLate",
     "not a Int value"),
    ({**TURN, "turn": {**TURN["turn"], "facts": {"refund": True}}}, "cases[0].turn.facts.refund", "derived"),
    ({**TURN, "turn": {**TURN["turn"], "facts": {"nope": 1}}}, "cases[0].turn.facts.nope", "unknown variable"),
    ({**TURN, "turn": {**TURN["turn"], "asked": "daysLate"}}, "cases[0].turn.asked", "not an ask variable"),
    ({**TURN, "turn": {**TURN["turn"], "message": True}}, "cases[0].turn.message", "expected text"),
    ({**TURN, "expect": {"decision": "jackpot"}}, "cases[0].expect.decision", "unknown outcome"),
    ({**TURN, "expect": {"decision": {"ask": "refund"}}}, "cases[0].expect.decision.ask", "not an ask variable"),
    ({**TURN, "expect": {"decision": "refund", "facts": {"wantsRefund": 2}}}, "cases[0].expect.facts.wantsRefund",
     "not a Bool value"),
    ({**TURN, "id": "bad id!"}, "cases[0].id", "letters, digits"),
    ({**TURN, "reply": REPLY["reply"]}, "cases[0]", "exactly one of turn or reply"),
    ({**REPLY, "expect": "maybe"}, "cases[0].expect", "caught or pass"),
    ({**TURN, "colour": 1}, "cases[0].colour", "unknown key"),
    ({**TURN, "turn": {**TURN["turn"], "facts": {"daysLate": 3, "wantsRefund": True}}}, "cases[0].turn.asked",
     "both asked and given"),
    ({**TURN, "turn": {**TURN["turn"], "facts": {"daysLate": 3, "carrier": "COURIER"}},
      "expect": {"decision": "refund", "facts": {"carrier": "COURIER"}}}, "cases[0].expect.facts.carrier",
     "already given"),
    ({**TURN, "expect": {"decision": "refund", "facts": {"refund": True}}}, "cases[0].expect.facts.refund",
     "derived"),
])
def test_bad_cases_name_the_path(case, path, message):
    got = decode(file(case), POLICIES)
    assert isinstance(got, Failure)
    err = got.failure()
    assert err.path == path and message in err.message, err


def test_case_ids_are_unique():
    assert decode(file(TURN, TURN), POLICIES) == Failure(CaseError("cases[1].id", "duplicate id 'plain-yes'"))


def test_a_broken_policy_is_reported_under_policy(tmp_path):
    (tmp_path / "p.yaml").write_text("policy: x\n")
    got = decode({"policy": "p.yaml", "cases": []}, tmp_path)
    assert isinstance(got, Failure) and got.failure().path == "policy"


def test_load_reports_unreadable_yaml(tmp_path):
    (tmp_path / "c.yaml").write_text("cases: [")
    got = load(tmp_path / "c.yaml")
    assert isinstance(got, Failure) and got.failure().path == "" and "YAML" in got.failure().message
    assert isinstance(load(tmp_path / "missing.yaml"), Failure)


def test_an_empty_case_list_is_fine():
    assert decode(file(), POLICIES).map(lambda f: f.cases) == Success(())
