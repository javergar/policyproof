from policyproof.core.prove import (
    Contingent,
    Inconsistent,
    Proven,
    Refuted,
    classify,
    entails,
    equivalent,
    premises,
)
from policyproof.core.solver import FactLabel, RuleLabel, compile
from policyproof.core.syntax import And, BoolLit, Cmp, IntLit, Not, Or, Var


def test_proven_with_the_rules_and_facts_used(toy):
    c = compile(toy)
    verdict = classify(c, Var("refund"), premises({"daysLate": IntLit(3), "wantsRefund": BoolLit(True)}))
    assert isinstance(verdict, Proven)
    assert {RuleLabel("T1"), RuleLabel("T2"), FactLabel("wantsRefund", BoolLit(True))} <= verdict.core


def test_refuted_and_contingent(toy):
    c = compile(toy)
    assert isinstance(classify(c, Var("voucher"), premises({"daysLate": IntLit(0)})), Refuted)
    verdict = classify(c, Var("refund"), premises({"daysLate": IntLit(3)}))
    assert isinstance(verdict, Contingent)
    assert verdict.when_true["refund"] == BoolLit(True) and verdict.when_false["refund"] == BoolLit(False)


def test_inconsistent_premises(toy):
    verdict = classify(compile(toy), Var("refund"), premises({"daysLate": IntLit(-2)}))
    assert verdict == Inconsistent(frozenset({RuleLabel("T6"), FactLabel("daysLate", IntLit(-2))}))


def test_entails_and_equivalent(toy):
    c = compile(toy)
    late = Cmp("ge", Var("daysLate"), IntLit(5))
    assert entails(c, [late, Var("wantsRefund")], Var("refund"))
    assert not entails(c, [late], Var("refund"))
    p, q = Var("wantsRefund"), Var("refund")
    assert equivalent(c, Not(And((p, q))), Or((Not(p), Not(q))))
    assert not equivalent(c, Var("refund"), Var("isLate"))
