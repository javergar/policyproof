from fractions import Fraction

from conftest import load
from returns.result import Failure, Success

from policyproof.core.syntax import BoolLit, EnumLit, IntLit, RealLit
from policyproof.guards.values import in_text, literal_for


def test_literal_for_reads_each_sort(toy):
    assert literal_for(toy, "wantsRefund", True) == Success(BoolLit(True))
    assert literal_for(toy, "wantsRefund", "false") == Success(BoolLit(False))
    assert literal_for(toy, "daysLate", 3) == Success(IntLit(3))
    assert literal_for(toy, "carrier", "COURIER") == Success(EnumLit("Carrier", "COURIER"))
    assert literal_for(toy, "carrier", "Carrier.POST") == Success(EnumLit("Carrier", "POST"))


def test_literal_for_reads_reals_exactly():
    p = load("weights.yaml")
    assert literal_for(p, "kg", {"real": "2.5"}) == Success(RealLit(Fraction(5, 2)))
    assert literal_for(p, "kg", 3) == Success(RealLit(Fraction(3)))
    assert isinstance(literal_for(p, "kg", {"real": "heavy"}), Failure)
    assert isinstance(literal_for(p, "kg", 2.5), Failure)  # floats are inexact: write {real: "2.5"}


def test_literal_for_rejects_the_wrong_sort_and_unknown_names(toy):
    for var, value in [("wantsRefund", 1), ("daysLate", True), ("daysLate", "3"), ("carrier", "TRUCK"),
                       ("nope", True), ("carrier", 1)]:
        assert isinstance(literal_for(toy, var, value), Failure), (var, value)


def test_in_text_ignores_case_and_punctuation_but_not_word_boundaries():
    assert in_text("Money back", "I'd like my money-back, please")
    assert not in_text("no", "I know")
    assert not in_text("  ", "anything")


def test_enum_values_match_in_any_case_when_unambiguous(toy):
    assert literal_for(toy, "carrier", "courier") == Success(EnumLit("Carrier", "COURIER"))
    assert literal_for(toy, "carrier", "carrier.post") == Success(EnumLit("Carrier", "POST"))


def test_quotes_match_across_straight_and_curly_apostrophes():
    assert in_text("I'd like my money back", "I\u2019d like my money back")
