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
from policyproof.core.syntax import BoolLit, EnumLit, IntLit, Not, RealLit, Var


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


FERMAT = """policy: fermat
version: "1"
variables:
  x: { sort: Int, role: system }
  y: { sort: Int, role: system }
  z: { sort: Int, role: system }
rules:
  - { id: F1, constraint: { and: [{ gt: [x, 0] }, { gt: [y, 0] }, { gt: [z, 0] }] } }
  - { id: F2, constraint: { eq: [{ add: [{ mul: [x, x, x] }, { mul: [y, y, y] }] }, { mul: [z, z, z] }] } }
"""


def _policy(text):
    from policyproof.core.codec import from_yaml
    return from_yaml(text).unwrap()


def test_the_solver_gives_up_instead_of_hanging():
    from policyproof.core.solver import Unknown
    assert isinstance(check(compile(_policy(FERMAT), timeout_ms=300), []), Unknown)


def test_a_variable_named_like_an_internal_tracker_is_harmless():
    p = _policy('policy: t\nversion: "1"\nvariables:\n  __track_0: { sort: Bool, role: system }\n'
                '  o: { sort: Bool, role: derived }\nrules:\n  - { id: R1, define: { var: o, as: __track_0 } }\n')
    assert isinstance(check(compile(p), [(ExtraLabel("x"), Not(Var("o")))]), Sat)


def test_an_irrational_model_value_is_approximated_not_a_crash():
    p = _policy('policy: t\nversion: "1"\nvariables:\n  x: { sort: Real, role: system }\n'
                'rules:\n  - { id: R1, constraint: { eq: [{ mul: [x, x] }, { real: "2" }] } }\n')
    result = check(compile(p), [])
    assert isinstance(result, Sat)
    x = result.model["x"]
    assert isinstance(x, RealLit) and abs(x.value * x.value - 2) < 1e-9
