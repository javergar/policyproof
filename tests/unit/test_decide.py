import z3

from policyproof.core.decide import Contradiction, Decided, Escalate, NeedInfo, decide
from policyproof.core.explain import explain
from policyproof.core.facts import Answered, Fact, FromSystem, Quoted, Scored, Volunteered, facts
from policyproof.core.solver import compile
from policyproof.core.syntax import BoolLit, Cmp, EnumLit, IntLit, Var

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
    said = Fact("wantsRefund", BoolLit(True), Volunteered(Quoted("I just want my money back")))
    d = decide(compile(toy), facts(sys("daysLate", IntLit(3)), said))
    assert isinstance(d, NeedInfo) and d.var == "wantsRefund" and d.reason == "confirm"


def test_a_scored_volunteered_fact_is_confirmed_like_a_quoted_one(toy):
    said = Fact("wantsRefund", BoolLit(True), Volunteered(Scored(0.97)))
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


OVERLAP = """policy: overlap
version: "1"
variables:
  late: { sort: Bool, role: system }
  wantsRefund: { sort: Bool, role: ask, question: "Would you like your money back?" }
  refund: { sort: Bool, role: derived }
  credit: { sort: Bool, role: derived }
rules:
  - { id: O1, define: { var: refund, as: { and: [late, wantsRefund] } } }
  - { id: O2, define: { var: credit, as: late } }
outcomes:
  full_refund: { refund: true }
  store_credit: { credit: true }
  nothing: { refund: false, credit: false }
"""


def test_a_later_outcome_waits_until_the_earlier_ones_are_ruled_out():
    """store_credit is proven by late alone, but full_refund comes first and might still hold."""
    from policyproof.core.codec import from_yaml
    c = compile(from_yaml(OVERLAP).unwrap())
    late = sys("late", BoolLit(True))
    assert decide(c, facts(late)) == NeedInfo("wantsRefund", "Would you like your money back?", "missing",
                                              ((BoolLit(True), "full_refund"), (BoolLit(False), "store_credit")))
    no = Fact("wantsRefund", BoolLit(False), YES)
    assert decide(c, facts(late, no)) == Decided("store_credit", ("O2",), (late,))


def test_with_system_facts_missing_only_a_question_that_settles_the_open_outcome_is_asked():
    """Retail store credit hangs on the return window (system facts not given): ask whether it was a final sale, since
    "yes" rules store credit out; once that can't help, escalate and name the missing facts, never asking the rest."""
    from conftest import load
    c = compile(load("retail_refund.yaml"))
    no_receipt = sys("hasProofOfPurchase", BoolLit(False))
    asked = decide(c, facts(no_receipt))
    assert isinstance(asked, NeedInfo) and asked.var == "isFinalSale"
    final = Answered(asked.question, "case")
    decided = decide(c, facts(no_receipt, Fact("isFinalSale", BoolLit(True), final)))
    assert isinstance(decided, Decided) and decided.outcome == "no_refund"
    stuck = decide(c, facts(no_receipt, Fact("isFinalSale", BoolLit(False), final)))
    assert isinstance(stuck, Escalate) and "store_credit" in stuck.reason and "daysSincePurchase" in stuck.reason


JOINT = """policy: joint
version: "1"
variables:
  late: { sort: Bool, role: system }
  a: { sort: Bool, role: ask, question: "Was it a gift?" }
  b: { sort: Bool, role: ask, question: "Was it wrapped?" }
  match: { sort: Bool, role: derived }
  credit: { sort: Bool, role: derived }
rules:
  - { id: J1, define: { var: match, as: { iff: [a, b] } } }
  - { id: J2, define: { var: credit, as: late } }
outcomes:
  matched: { match: true }
  credit: { credit: true }
  nothing: { match: false, credit: false }
"""


def test_an_open_outcome_two_answers_settle_together_is_asked_about_not_escalated():
    """`matched` hangs on a ⇔ b: no single answer settles it, but a and then b do."""
    from policyproof.core.codec import from_yaml
    c = compile(from_yaml(JOINT).unwrap())
    late = sys("late", BoolLit(True))
    first = decide(c, facts(late))
    assert isinstance(first, NeedInfo) and first.var == "a"
    gift = Fact("a", BoolLit(True), Answered(first.question, "yes"))
    assert decide(c, facts(late, gift)) == NeedInfo("b", "Was it wrapped?", "missing",
                                                    ((BoolLit(True), "matched"), (BoolLit(False), "credit")))


def test_decide_stops_looking_for_joint_answers_after_the_cap(monkeypatch):
    from policyproof.core import decide as decide_module
    from policyproof.core.codec import from_yaml
    monkeypatch.setattr(decide_module, "JOINT_TRIES", 4)  # a and b alone: 4 tries; the pair would need 4 more
    d = decide(compile(from_yaml(JOINT).unwrap()), facts(sys("late", BoolLit(True))))
    assert d == Escalate("outcome matched may still hold, and decide stopped looking for questions that settle it "
                         "after 4 combinations of answers")


def test_an_open_outcome_the_solver_gives_up_on_escalates(monkeypatch):
    from policyproof.core import decide as decide_module
    from policyproof.core.codec import from_yaml
    from policyproof.core.solver import Unknown
    monkeypatch.setattr(decide_module, "decidable", lambda *_, **__: Unknown("timeout"))
    d = decide(compile(from_yaml(OVERLAP).unwrap()), facts(sys("late", BoolLit(True))))
    assert d == Escalate("the solver gave up on outcome full_refund: timeout")


def test_a_policy_without_outcomes_escalates():
    from policyproof.core.codec import from_yaml
    p = from_yaml(EDGE.split("outcomes:")[0]).unwrap()
    assert isinstance(decide(compile(p), facts(Fact("n", IntLit(5), OPS), Fact("bags", IntLit(2), YES))), Escalate)


def test_facts_on_derived_variables_and_ill_typed_facts_are_rejected(toy):
    from policyproof.core.decide import InvalidFacts
    c = compile(toy)
    for bad in (Fact("refund", BoolLit(True), Volunteered(Quoted("I get a refund"))),
                Fact("nope", BoolLit(True), OPS),
                Fact("wantsRefund", IntLit(1), YES),
                Fact("carrier", EnumLit("Carrier", "PLANE"), OPS)):
        assert isinstance(decide(c, facts(bad)), InvalidFacts), bad


def test_a_volunteered_system_fact_never_decides(toy):
    said = Fact("daysLate", IntLit(5), Volunteered(Quoted("it was five days late")))
    d = decide(compile(toy), facts(said, Fact("wantsRefund", BoolLit(True), YES)))
    assert not isinstance(d, Decided)


def test_contradicting_volunteered_statements_lead_to_a_question(toy):
    d = decide(compile(toy), facts(sys("daysLate", IntLit(3)),
                                   Fact("wantsRefund", BoolLit(True), Volunteered(Quoted("refund please"))),
                                   Fact("wantsRefund", BoolLit(False), Volunteered(Quoted("a voucher is fine")))))
    assert isinstance(d, NeedInfo) and d.var == "wantsRefund" and d.reason == "confirm"


def test_no_outcomes_escalates_before_asking():
    from policyproof.core.codec import from_yaml
    p = from_yaml(EDGE.split("outcomes:")[0]).unwrap()
    assert isinstance(decide(compile(p), facts(Fact("n", IntLit(5), OPS))), Escalate)


def test_an_int_question_is_asked_last():
    from policyproof.core.codec import from_yaml
    p = from_yaml("""policy: t
version: "1"
variables:
  n: { sort: Int, role: ask, question: "How many?" }
  b: { sort: Bool, role: ask, question: "B?" }
  ok: { sort: Bool, role: derived }
rules:
  - { id: R1, when: { and: [{ gt: [n, 1] }, b] }, then: ok }
outcomes:
  ok: { ok: true }
""").unwrap()
    d = decide(compile(p), facts())
    assert isinstance(d, NeedInfo) and d.var == "b"


def test_an_outcome_the_solver_cant_settle_escalates_rather_than_skipping_to_the_next(toy, monkeypatch):
    """Solver timing can't pin this down, so the first outcome's classification is replaced with a give-up."""
    import policyproof.core.decide as decide_module
    from policyproof.core.prove import Undetermined, classify

    def gives_up_on_refund(c, claim, assertions=(), **kw):
        return Undetermined("canceled") if claim == Cmp("eq", Var("refund"), BoolLit(True)) else classify(
            c, claim, assertions, **kw)

    monkeypatch.setattr(decide_module, "classify", gives_up_on_refund)
    known = facts(sys("daysLate", IntLit(3)), Fact("wantsRefund", BoolLit(False), YES))
    assert isinstance(decide(compile(toy), known), Escalate)
