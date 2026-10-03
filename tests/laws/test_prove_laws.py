"""L4 (Z3 half) and L7: `classify` agrees with enumerating every world."""
from typing import assert_never

from hypothesis import given
from hypothesis import strategies as st
from oracle import judge
from strategies import COLOR, DECLS, FINITE, exprs, finite_rule_sets, literals

from policyproof.core.prove import (
    Contingent,
    Inconsistent,
    Proven,
    Refuted,
    Undetermined,
    Verdict,
    classify,
    equivalent,
    premises,
)
from policyproof.core.semantics import simplify
from policyproof.core.solver import compile
from policyproof.core.syntax import BOOL, Policy
from policyproof.core.typecheck import check_policy

EMPTY = compile(check_policy(Policy("laws", "1", (COLOR,), DECLS, (), ())).unwrap())


def name(v: Verdict) -> str:
    match v:
        case Proven():
            return "proven"
        case Refuted():
            return "refuted"
        case Contingent():
            return "contingent"
        case Inconsistent():
            return "inconsistent"
        case Undetermined():
            return "undetermined"
        case _:
            assert_never(v)

GIVEN = st.dictionaries(st.sampled_from(FINITE), st.none()).flatmap(lambda d: st.fixed_dictionaries(
    {k: literals(COLOR) if k == "c" else literals(BOOL) for k in d}))


@given(exprs(BOOL))
def test_l4_simplify_is_equivalent_according_to_z3(e):
    assert equivalent(EMPTY, e, simplify(e))


@given(finite_rule_sets(), GIVEN, exprs(BOOL, 3, finite=True))
def test_l7_classify_agrees_with_the_oracle(rules, facts, claim):
    c = compile(check_policy(Policy("oracle", "1", (COLOR,), DECLS, rules, ())).unwrap())
    verdict = classify(c, claim, premises(facts))
    assert name(verdict) == judge(rules, facts, claim)
