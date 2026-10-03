import z3

from policyproof.core.decide import Contradiction, Decided, Escalate, NeedInfo, decide
from policyproof.core.explain import explain
from policyproof.core.facts import Answered, Fact, FromSystem, Volunteered, facts
from policyproof.core.solver import compile
from policyproof.core.syntax import BoolLit, EnumLit, IntLit

OPS = FromSystem("parcel tracking")
YES = Answered("Would you like your money back?", "yes please")


def sys(var, value):
    return Fact(var, value, OPS)


def test_decided_with_the_rules_and_facts_used(toy):
    d = decide(compile(toy), facts(sys("daysLate", IntLit(3)), Fact("wantsRefund", BoolLit(True), YES)))
    assert isinstance(d, Decided) and d.outcome == "refund"
    assert {"T1", "T2"} <= set(d.rules)
    assert {f.var for f in d.facts_used} == {"daysLate", "wantsRefund"}


def test_decided_without_asking_when_the_answer_doesnt_matter(toy):
    d = decide(compile(toy), facts(sys("daysLate", IntLit(0))))
    assert isinstance(d, Decided) and d.outcome == "nothing"


def test_asks_the_question_that_settles_it(toy):
    d = decide(compile(toy), facts(sys("daysLate", IntLit(3))))
    assert d == NeedInfo("wantsRefund", "Would you like your money back?", "missing",
                         ((BoolLit(True), "refund"), (BoolLit(False), "voucher")))


def test_a_volunteered_fact_is_confirmed_before_it_decides(toy):
    said = Fact("wantsRefund", BoolLit(True), Volunteered("I just want my money back"))
    d = decide(compile(toy), facts(sys("daysLate", IntLit(3)), said))
    assert isinstance(d, NeedInfo) and d.var == "wantsRefund" and d.reason == "confirm"


def test_an_unclear_answer_is_asked_again(toy):
    d = decide(compile(toy), facts(sys("daysLate", IntLit(3))), unclear=frozenset({"wantsRefund"}))
    assert isinstance(d, NeedInfo) and d.reason == "unclear"


def test_a_courier_is_late_after_one_day(toy):
    d = decide(compile(toy), facts(sys("daysLate", IntLit(1)), sys("carrier", EnumLit("Carrier", "COURIER")),
                                   Fact("wantsRefund", BoolLit(False), YES)))
    assert isinstance(d, Decided) and d.outcome == "voucher"


def test_contradictions_name_rules_and_facts(toy):
    assert decide(compile(toy), facts(sys("daysLate", IntLit(-1)))) == Contradiction(
        ("T6",), (sys("daysLate", IntLit(-1)),))
    d = decide(compile(toy), facts(sys("daysLate", IntLit(1)), sys("daysLate", IntLit(3))))
    assert isinstance(d, Contradiction) and d.rules == () and len(d.facts) == 2


def test_escalates_when_nothing_is_left_to_ask(toy):
    d = decide(compile(toy), facts(Fact("wantsRefund", BoolLit(True), YES)))
    assert isinstance(d, Escalate)


def test_the_trace_is_a_runnable_proof(toy):
    c = compile(toy)
    fs = facts(sys("daysLate", IntLit(3)), Fact("wantsRefund", BoolLit(True), YES))
    d = decide(c, fs)
    assert isinstance(d, Decided)
    trace = explain(c, d, fs)
    assert trace.expected == "unsat" and [s.rule for s in trace.steps] == list(d.rules)
    assert trace.steps[0].premise.startswith("daysLate ≥ 2")
    s = z3.Solver()
    s.from_string(trace.smtlib.removesuffix("(check-sat)"))
    assert s.check() == z3.unsat


EDGE = """policy: edge
version: "1"
variables:
  n: { sort: Int, role: system }
  bags: { sort: Int, role: ask, question: "How many bags did you check in?" }
  big: { sort: Bool, role: derived }
  fee: { sort: Bool, role: derived }
rules:
  - { id: E1, define: { var: big, as: { ge: [{ mul: [n, n] }, 16] } } }
  - { id: E2, when: { and: [big, { gt: [bags, 1] }] }, then: fee }
  - { id: E3, when: { not: big }, then: { not: fee } }
outcomes:
  fee: { fee: true }
  no_fee: { fee: false }
"""


def edge():
    from policyproof.core.codec import from_yaml
    return compile(from_yaml(EDGE).unwrap())


def test_non_linear_arithmetic_still_decides():
    d = decide(edge(), facts(Fact("n", IntLit(3), OPS)))
    assert isinstance(d, Decided) and d.outcome == "no_fee"


def test_an_int_question_has_no_what_if_table_but_is_still_asked():
    d = decide(edge(), facts(Fact("n", IntLit(5), OPS)))
    assert d == NeedInfo("bags", "How many bags did you check in?", "missing", ())
    answered = facts(Fact("n", IntLit(5), OPS), Fact("bags", IntLit(2), Answered("How many bags?", "two")))
    assert decide(edge(), answered) == Decided("fee", ("E1", "E2"), tuple(sorted(
        [Fact("bags", IntLit(2), Answered("How many bags?", "two")), Fact("n", IntLit(5), OPS)], key=repr)))


def test_a_policy_without_outcomes_escalates():
    from policyproof.core.codec import from_yaml
    p = from_yaml(EDGE.split("outcomes:")[0]).unwrap()
    assert isinstance(decide(compile(p), facts(Fact("n", IntLit(5), OPS), Fact("bags", IntLit(2), YES))), Escalate)
