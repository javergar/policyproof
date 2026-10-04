"""E3: consensus is commutative (up to which side's evidence or quote is kept) and idempotent; agreeing keeps no more
than either side, and the union drops nothing."""
from conftest import load
from hypothesis import given
from hypothesis import strategies as st

from policyproof.core.facts import Quoted, Scored
from policyproof.effects.consensus import agree_answers, agree_facts, union_claims
from policyproof.effects.ports import NotAnswered, RawClaim, RawFact, Said, Unclear
from policyproof.guards.values import literal_for

TOY = load("toy.yaml")
MSG = "yes money back by courier"
EVIDENCE = st.one_of(st.builds(Quoted, st.sampled_from(["yes", "money back", "nowhere"])),
                     st.builds(Scored, st.sampled_from([0.2, 0.6, 0.9])))
FACTS = st.lists(st.builds(RawFact, st.sampled_from(["wantsRefund", "carrier", "daysLate"]),
                           st.sampled_from([True, False, "true", "COURIER", "POST", 2, 3]), EVIDENCE), max_size=5)
ANSWERS = st.one_of(st.builds(Said, st.sampled_from([True, False, "true", "false", 7]),
                              st.sampled_from(["yes", "money back", "nowhere"])),
                    st.just(NotAnswered()), st.builds(Unclear, st.sampled_from(["a", "b"])))
CLAIMS = st.lists(st.builds(RawClaim, st.sampled_from(["refund", {"not": "voucher"}, True]),
                            st.sampled_from(["q1", "q2"])), max_size=4)


def keys(fs):
    return {(f.var, literal_for(TOY, f.var, f.value).value_or(None)) for f in fs}


@given(FACTS, FACTS)
def test_e3_agreeing_facts_is_commutative_and_keeps_no_more_than_either(a, b):
    ab, ba = agree_facts(TOY, a, b), agree_facts(TOY, b, a)
    assert keys(ab) == keys(ba)
    assert keys(ab) <= keys(a) and keys(ab) <= keys(b)


@given(FACTS)
def test_e3_agreeing_facts_is_idempotent(a):
    aa = agree_facts(TOY, a, a)
    assert agree_facts(TOY, aa, aa) == aa
    assert keys(aa) == keys(a) - {(f.var, None) for f in a}


@given(ANSWERS, ANSWERS)
def test_e3_agreeing_answers_is_commutative_up_to_the_quote(a, b):
    ab, ba = agree_answers(TOY, "wantsRefund", MSG, a, b), agree_answers(TOY, "wantsRefund", MSG, b, a)
    assert type(ab) is type(ba)


@given(ANSWERS)
def test_e3_agreeing_answers_is_idempotent(a):
    assert agree_answers(TOY, "wantsRefund", MSG, a, a) == a


@given(CLAIMS, CLAIMS)
def test_e3_the_claim_union_is_commutative_up_to_order_and_drops_nothing(a, b):
    ab, ba = union_claims(a, b), union_claims(b, a)
    assert set(map(repr, ab)) == set(map(repr, ba)) == set(map(repr, [*a, *b]))
    assert union_claims(ab, ab) == ab
