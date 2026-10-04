from policyproof.core.facts import Answered, Fact
from policyproof.core.syntax import BoolLit
from policyproof.guards.answer import Answer, check, opening_word
from policyproof.guards.raw import NotAnswered, Said, Unclear

Q = "Would you like your money back?"


def test_an_answer_becomes_an_answered_fact(toy):
    got = check(toy, "wantsRefund", "Yes please, money back.", Said(True, "money back"))
    assert got == Answer(Fact("wantsRefund", BoolLit(True), Answered(Q, "money back")))


def test_a_quote_that_is_not_in_the_message_is_unclear(toy):
    assert check(toy, "wantsRefund", "Yes please.", Said(True, "refund me")) == Unclear("quote not in message")


def test_a_value_of_the_wrong_sort_is_unclear(toy):
    got = check(toy, "wantsRefund", "Yes please.", Said("COURIER", "Yes please"))
    assert isinstance(got, Unclear) and "not a Bool" in got.reason


def test_an_opening_word_that_contradicts_the_value_is_unclear(toy):
    got = check(toy, "wantsRefund", "Yes, a voucher is fine.", Said(False, "a voucher is fine"))
    assert got == Unclear("opening contradicts answer")


def test_only_askable_variables_can_be_answered(toy):
    assert check(toy, "daysLate", "3 days", Said(3, "3 days")) == Unclear("not an askable variable")
    assert check(toy, "refund", "yes", Said(True, "yes")) == Unclear("not an askable variable")


def test_unclear_and_not_answered_pass_through(toy):
    assert check(toy, "wantsRefund", "hmm", Unclear("hedged")) == Unclear("hedged")
    assert check(toy, "wantsRefund", "when is it?", NotAnswered()) == NotAnswered()


def test_opening_word_is_none_without_a_plain_yes_or_no():
    assert opening_word("  YES!") is True
    assert opening_word("Noted") is None
