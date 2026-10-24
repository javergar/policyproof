"""P1 to P3: the problem finder's customers are real and minimal, and it agrees with the validator."""
from hypothesis import given, settings
from hypothesis import strategies as st
from strategies import COLOR, DECLS, finite_rule_sets

from policyproof.core.problems import Clash, problems
from policyproof.core.semantics import rule_expr
from policyproof.core.solver import RuleLabel, Unsat, check, compile, fact
from policyproof.core.syntax import BoolLit, Outcome, Policy
from policyproof.core.typecheck import check_policy
from policyproof.core.validate import Conflict, NotTotal, SolverGaveUp, Undecided, validate

OUTCOMES = st.sampled_from([
    (),
    (Outcome("yes", (("r", BoolLit(True)),)),),
    (Outcome("yes", (("r", BoolLit(True)),)), Outcome("no", (("r", BoolLit(False)),))),
])


def compiled(rules, outcomes):
    return compile(check_policy(Policy("laws", "1", (COLOR,), DECLS, rules, outcomes)).unwrap())


def clash_holds(c, f: Clash, customer) -> bool:
    """Whether the clash's own rules can't hold together with these facts."""
    by_id = {r.id: r for r in c.policy.rules}
    own = [(RuleLabel(i), rule_expr(by_id[i])) for i in f.rules]
    return isinstance(check(c, [*own, *(fact(v, x) for v, x in customer)], rules=False), Unsat)


@settings(max_examples=50)
@given(finite_rule_sets(), OUTCOMES)
def test_p1_a_clash_customer_clashes_and_needs_every_fact(rules, outcomes):
    c = compiled(rules, outcomes)
    for f in problems(c).found:
        if isinstance(f, Clash):
            assert clash_holds(c, f, f.customer)
            for dropped in f.customer:
                assert not clash_holds(c, f, [x for x in f.customer if x != dropped])


@settings(max_examples=50)
@given(finite_rule_sets(), OUTCOMES)
def test_p2_a_witness_extends_its_customer(rules, outcomes):
    for f in problems(compiled(rules, outcomes)).found:
        if isinstance(f, Clash):
            assert set(f.customer) <= set(f.witness)


@settings(max_examples=50)
@given(finite_rule_sets(), OUTCOMES)
def test_p3_no_problems_exactly_when_the_validator_finds_none(rules, outcomes):
    c = compiled(rules, outcomes)
    result = problems(c)
    flagged = [f for f in validate(c) if isinstance(f, Conflict | NotTotal | Undecided | SolverGaveUp)]
    assert (result.found == () and result.complete) == (flagged == [])
