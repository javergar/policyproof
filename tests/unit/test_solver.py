from policyproof.core.solver import (
    ExtraLabel,
    FactLabel,
    RuleLabel,
    Sat,
    Unsat,
    check,
    compile,
    fact,
)
from policyproof.core.syntax import BoolLit, EnumLit, IntLit, Not, Var


def test_rules_alone_are_satisfiable(toy):
    assert isinstance(check(compile(toy), []), Sat)


def test_a_model_assigns_every_variable(toy):
    result = check(compile(toy), [fact("daysLate", IntLit(3)), fact("wantsRefund", BoolLit(True))])
    assert isinstance(result, Sat)
    assert result.model["isLate"] == BoolLit(True) and result.model["refund"] == BoolLit(True)
    assert result.model["carrier"] in (EnumLit("Carrier", "POST"), EnumLit("Carrier", "COURIER"))


def test_unsat_core_names_rules_and_facts(toy):
    late = [fact("daysLate", IntLit(3)), fact("wantsRefund", BoolLit(True))]
    result = check(compile(toy), [*late, (ExtraLabel("claim"), Not(Var("refund")))])
    assert isinstance(result, Unsat)
    assert result.core >= {RuleLabel("T1"), RuleLabel("T2"), ExtraLabel("claim"),
                           FactLabel("daysLate", IntLit(3)), FactLabel("wantsRefund", BoolLit(True))}


def test_constraints_are_rules(toy):
    result = check(compile(toy), [fact("daysLate", IntLit(-1))])
    assert result == Unsat(frozenset({RuleLabel("T6"), FactLabel("daysLate", IntLit(-1))}))


def test_rules_can_be_left_out(toy):
    assert isinstance(check(compile(toy), [fact("daysLate", IntLit(-1))], rules=False), Sat)


def test_each_policy_gets_its_own_context(toy):
    a, b = compile(toy), compile(toy)
    assert a.ctx is not b.ctx
