"""Parity with the demo's answer check (decision/handler.py: `opening_word`, `read_answer`), on the demo's own test
cases (tests/test_handler.py), copied here so this test doesn't need the demo's AWS dependencies."""
import pytest
from conftest import load

from policyproof.core.syntax import BoolLit
from policyproof.guards.answer import Answer, check, opening_word
from policyproof.guards.raw import Said, Unclear


@pytest.mark.parametrize(("reply", "lead"), [
    ("No, I'll make other plans. I don't want to travel any more.", False),
    ("Yes, that's right, please cancel it.", True),
    ("That\u2019s right, cancel it", True),
    ("Nope", False), ("yeah go ahead", True), ("I'd rather not, honestly", None), ("Noted, thanks", None),
])
def test_opening_word(reply, lead):
    assert opening_word(reply) is lead


def test_a_reply_contradicting_its_opening_word_is_unclear():
    p = load("flight_disruption.yaml")
    got = check(p, "wantsToTravel", "Yes, that's right, please cancel it.", Said("false", "please cancel it"))
    assert got == Unclear("opening contradicts answer")
    got = check(p, "wantsToTravel", "No, please cancel it.", Said("false", "please cancel it"))
    assert isinstance(got, Answer) and got.fact.value == BoolLit(False)
