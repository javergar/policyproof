from policyproof.core.facts import Fact, Quoted, Scored, Volunteered, all_facts
from policyproof.core.syntax import BoolLit, EnumLit
from policyproof.guards.facts import check
from policyproof.guards.raw import RawFact, Rejected

MSG = "It came by courier and I'd like my money back."


def test_quoted_and_confident_facts_are_kept(toy):
    kept, rejected = check(toy, MSG, (RawFact("carrier", "COURIER", Quoted("by courier")),
                                      RawFact("wantsRefund", "true", Scored(0.9))))
    assert all_facts(kept) == (Fact("carrier", EnumLit("Carrier", "COURIER"), Volunteered(Quoted("by courier"))),
                               Fact("wantsRefund", BoolLit(True), Volunteered(Scored(0.9))))
    assert rejected == ()


def test_unsupported_facts_are_rejected_with_a_reason(toy):
    kept, rejected = check(toy, MSG, (
        RawFact("carrier", "POST", Quoted("by post")),           # quote not in the message
        RawFact("wantsRefund", True, Scored(0.4)),               # not confident enough
        RawFact("refund", True, Quoted("money back")),           # derived: the rules decide it
        RawFact("daysLate", "three", Quoted("courier")),         # wrong sort
        RawFact("colour", "RED", Quoted("courier")),             # not a variable
    ))
    assert kept == {}
    assert [r.item for r in rejected] == ["carrier", "wantsRefund", "refund", "daysLate", "colour"]
    assert rejected[0] == Rejected("carrier", "quote not in message")
    assert rejected[1] == Rejected("wantsRefund", "confidence 0.4 is below 0.5")
    assert rejected[2] == Rejected("refund", "refund is derived by the rules; it can't be given as a fact")


def test_the_confidence_bar_is_a_parameter(toy):
    kept, _ = check(toy, MSG, (RawFact("wantsRefund", True, Scored(0.4)),), min_confidence=0.3)
    assert "wantsRefund" in kept


def test_conflicting_facts_are_both_kept_for_decide_to_report(toy):
    kept, _ = check(toy, "money back, or a voucher", (RawFact("wantsRefund", True, Quoted("money back")),
                                                    RawFact("wantsRefund", False, Quoted("a voucher"))))
    assert len(kept["wantsRefund"]) == 2
