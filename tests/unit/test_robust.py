import pytest
from conftest import POLICIES

from policyproof.core.codec import from_yaml
from policyproof.core.decide import Decided, NeedInfo, decide, what_if
from policyproof.core.facts import Fact, FromSystem, Quoted, Scored, Volunteered, facts
from policyproof.core.solver import compile
from policyproof.core.syntax import BoolLit, IntLit
from policyproof.guards.robust import decide_robustly

LATE = Fact("daysLate", IntLit(3), FromSystem("tracking"))


@pytest.fixture(scope="module")
def trusting():
    """The toy policy, but a refund preference said in passing counts without confirmation."""
    question = "question: Would you like your money back?"
    text = (POLICIES / "toy.yaml").read_text().replace(question, f"{question}\n    confirm_volunteered: false")
    return compile(from_yaml(text).unwrap())


def said(confidence: float) -> Fact:
    return Fact("wantsRefund", BoolLit(True), Volunteered(Scored(confidence)))


def test_a_confident_fact_decides(trusting):
    d = decide_robustly(trusting, facts(LATE, said(0.9)))
    assert isinstance(d, Decided) and d.outcome == "refund"


def test_a_weak_fact_that_would_decide_is_confirmed_first(trusting):
    d = decide_robustly(trusting, facts(LATE, said(0.6)))
    assert d == NeedInfo("wantsRefund", "Would you like your money back?", "confirm",
                         what_if(trusting, (LATE,), "wantsRefund"))
    assert isinstance(decide(trusting, facts(LATE, said(0.6))), Decided)  # plain decide would have used it


def test_a_weak_fact_that_changes_nothing_is_kept(trusting):
    on_time = Fact("daysLate", IntLit(0), FromSystem("tracking"))
    d = decide_robustly(trusting, facts(on_time, said(0.6)))
    assert isinstance(d, Decided) and d.outcome == "nothing"


def test_the_bar_is_a_parameter(trusting):
    assert isinstance(decide_robustly(trusting, facts(LATE, said(0.6)), firm_confidence=0.5), Decided)


def test_weak_facts_nobody_can_be_asked_about_are_ignored(trusting):
    weak_system = Fact("daysLate", IntLit(9), Volunteered(Scored(0.6)))
    quoted = Fact("wantsRefund", BoolLit(True), Volunteered(Quoted("money back")))
    assert decide_robustly(trusting, facts(weak_system, quoted)) == decide(trusting, facts(quoted))
