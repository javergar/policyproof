"""Facts and outcomes in plain words, for authors who don't read logic."""
from dataclasses import replace

from policyproof.authoring.plain import customer_phrases, outcome_label, phrase
from policyproof.core.syntax import BoolLit, EnumLit, IntLit, Outcome, Template, ValuePhrases


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
