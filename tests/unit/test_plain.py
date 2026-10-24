"""Facts and outcomes in plain words, for authors who don't read logic."""
from dataclasses import replace

from conftest import load

from policyproof.authoring.plain import customer_phrases, outcome_label, phrase, verdict
from policyproof.core.problems import Clash, Says, problems
from policyproof.core.solver import compile
from policyproof.core.syntax import BoolLit, CheckedPolicy, EnumLit, IntLit, Outcome, Template, ValuePhrases


def var(p, name):
    return next(v for v in p.variables if v.name == name)


def test_phrases_use_the_display(toy):
    carrier = replace(var(toy, "carrier"), display=ValuePhrases(((EnumLit("Carrier", "COURIER"), "Came by courier"),)))
    days = replace(var(toy, "daysLate"), display=Template("{} days late"))
    assert phrase(carrier, EnumLit("Carrier", "COURIER")) == "Came by courier"
    assert phrase(days, IntLit(3)) == "3 days late"


def test_phrases_fall_back_to_the_description(toy):
    assert phrase(var(toy, "carrier"), EnumLit("Carrier", "COURIER")) == "Who delivered the parcel: COURIER"
    assert phrase(var(toy, "wantsRefund"), BoolLit(True)) == (
        "True if the customer wants a refund rather than a voucher: yes")
    # a value the display doesn't cover falls back too
    carrier = replace(var(toy, "carrier"), display=ValuePhrases(((EnumLit("Carrier", "COURIER"), "Came by courier"),)))
    assert phrase(carrier, EnumLit("Carrier", "POST")) == "Who delivered the parcel: POST"


def test_customer_phrases_follow_the_customer(toy):
    assert customer_phrases(toy, (("daysLate", IntLit(3)), ("wantsRefund", BoolLit(False)))) == (
        "Days the parcel arrived after the promised date: 3",
        "True if the customer wants a refund rather than a voucher: no")


def test_outcome_label():
    assert outcome_label(Outcome("refund", (), "A refund")) == "A refund"
    assert outcome_label(Outcome("noRefund", ())) == "No refund"
    assert outcome_label(Outcome("store_credit", ())) == "Store credit"


def test_verdicts_in_plain_words():
    policy = load("defects/couriers.yaml")
    c = compile(policy)
    clash = next(f for f in problems(c).found if isinstance(f, Clash) and f.rules == ("C4", "C5"))
    said = {s.rule: verdict(policy, s) for s in clash.says}
    assert said == {"C4": ("Nothing", "no"), "C5": ("Refund", "yes")}
    assert verdict(policy, Says("C9", ())) == ("Can't hold together with the others", "none")
    c4 = next(s for s in clash.says if s.rule == "C4")
    assert verdict(CheckedPolicy(replace(policy, outcomes=policy.outcomes[:1])), c4) == ("No refund", "no")
    shown = replace(policy.outcomes[0], display="A refund")
    assert verdict(CheckedPolicy(replace(policy, outcomes=(shown,))), c4) == ("Not a refund", "no")
