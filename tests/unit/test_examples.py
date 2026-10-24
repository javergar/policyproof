"""Approved example customers: saved with the policy, and checked after every change."""
from returns.result import Failure

from policyproof.authoring.examples import Example, broken, dumps, holds, loads
from policyproof.core.solver import compile
from policyproof.core.syntax import BoolLit, EnumLit, IntLit

TEXT = """examples:
- id: late-post-asked
  customer:
    carrier: POST
    daysLate: 3
    wantsRefund: true
  outcome: refund
"""
LATE = Example("late-post-asked", (("carrier", EnumLit("Carrier", "POST")), ("daysLate", IntLit(3)),
                                   ("wantsRefund", BoolLit(True))), "refund")


def test_examples_round_trip_and_hold(toy):
    examples = loads(toy, TEXT).unwrap()
    assert examples == (LATE,)
    assert dumps(examples) == TEXT
    c = compile(toy)
    assert holds(c, LATE)
    wrong = Example("late-post-asked", LATE.customer, "voucher")
    assert broken(c, [LATE, wrong]) == (wrong,)


def test_an_example_that_doesnt_decide_is_broken(toy):
    # with no daysLate, the toy policy can't decide
    assert not holds(compile(toy), Example("unknown", (("wantsRefund", BoolLit(True)),), "refund"))


def failure(toy, text: str) -> str:
    result = loads(toy, text)
    assert isinstance(result, Failure), result
    return result.failure()


def test_bad_examples_name_the_problem(toy):
    one = "examples:\n- id: {id}\n  customer: {{{customer}}}\n  outcome: {outcome}\n"
    assert "e1" in (m := failure(toy, one.format(id="e1", customer="nope: 1", outcome="refund"))) and "nope" in m
    assert "isLate" in failure(toy, one.format(id="e1", customer="isLate: true", outcome="refund"))
    assert "daysLate" in failure(toy, one.format(id="e1", customer="daysLate: lots", outcome="refund"))
    assert "jackpot" in failure(toy, one.format(id="e1", customer="daysLate: 1", outcome="jackpot"))
    twice = one.format(id="e1", customer="daysLate: 1", outcome="refund") + one.format(
        id="e1", customer="daysLate: 2", outcome="refund").removeprefix("examples:\n")
    assert "e1" in failure(toy, twice) and "twice" in failure(toy, twice)
    assert "examples" in failure(toy, "examples: 3\n")
