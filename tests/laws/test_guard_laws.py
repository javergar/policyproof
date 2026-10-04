"""E2: guards are sound (what they keep is verified) and lossless (everything is kept or rejected with a reason)."""
from conftest import load
from hypothesis import given
from hypothesis import strategies as st
from returns.result import Success

from policyproof.core.decide import decide
from policyproof.core.facts import Answered, Fact, FromSystem, Quoted, Scored, Volunteered, all_facts
from policyproof.core.facts import facts as make_facts
from policyproof.core.semantics import free_vars
from policyproof.core.solver import compile
from policyproof.core.syntax import BOOL, BoolLit, Derived, IntLit
from policyproof.core.typecheck import signature, sort_of
from policyproof.guards import answer, claims, facts
from policyproof.guards.raw import NotAnswered, RawClaim, RawFact, Said, Unclear
from policyproof.guards.robust import decide_robustly
from policyproof.guards.values import in_text

TOY = load("toy.yaml")
SIG = signature(TOY)
WORDS = ["courier", "post", "late", "money", "back", "voucher", "yes", "no", "3", "days"]
MESSAGES = st.lists(st.sampled_from(WORDS), min_size=1, max_size=8).map(" ".join)
QUOTES = st.lists(st.sampled_from(WORDS), min_size=1, max_size=3).map(" ".join)
NAMES = st.sampled_from([v.name for v in TOY.variables] + ["junk"])
VALUES = st.one_of(st.booleans(), st.integers(-2, 5), st.sampled_from(["COURIER", "POST", "true", "x"]))
EVIDENCE = st.one_of(st.builds(Quoted, QUOTES), st.builds(Scored, st.floats(0, 1)))
RAW_FACTS = st.lists(st.builds(RawFact, NAMES, VALUES, EVIDENCE), max_size=6)
LEAVES = st.one_of(NAMES, st.sampled_from(["COURIER", "POST"]), st.integers(0, 4), st.booleans())
EXPRS = st.recursive(LEAVES, lambda e: st.one_of(
    st.builds(lambda a: {"not": a}, e),
    st.builds(lambda op, xs: {op: xs}, st.sampled_from(["and", "or", "eq", "ge", "add"]), st.lists(e, min_size=2,
                                                                                                    max_size=2))),
    max_leaves=6)
RAW_CLAIMS = st.lists(st.builds(RawClaim, EXPRS, QUOTES), max_size=5)
ROLE = {v.name: v for v in TOY.variables}


@given(MESSAGES, RAW_FACTS, st.floats(0, 1))
def test_e2_kept_facts_are_verified_and_nothing_is_lost(message, raws, bar):
    kept, rejected = facts.check(TOY, message, raws, min_confidence=bar)
    for f in all_facts(kept):
        assert not isinstance(ROLE[f.var].role, Derived)
        assert sort_of(SIG, f.value) == Success(ROLE[f.var].sort)
        assert isinstance(f.provenance, Volunteered)
        match f.provenance.evidence:
            case Quoted(text):
                assert in_text(text, message)
            case Scored(confidence):
                assert confidence >= bar
    dropped = {r.item for r in rejected}
    for r in raws:
        assert r.var in dropped or any(f.provenance == Volunteered(r.evidence) for f in kept.get(r.var, ()))


@given(MESSAGES, RAW_CLAIMS)
def test_e2_kept_claims_are_checkable_and_nothing_is_lost(reply, raws):
    kept, rejected = claims.check(TOY, reply, raws)
    for c in kept:
        assert sort_of(SIG, c.expr) == Success(BOOL)
        assert free_vars(c.expr)
        assert in_text(c.quote, reply)
    assert len(kept) + len(rejected) == len(raws)


@given(MESSAGES, st.one_of(st.builds(Said, VALUES, QUOTES), st.just(NotAnswered()), st.just(Unclear("u"))))
def test_e2_an_accepted_answer_is_verified(message, raw):
    got = answer.check(TOY, "wantsRefund", message, raw)
    if isinstance(got, answer.Answer):
        assert isinstance(got.fact.provenance, Answered) and in_text(got.fact.provenance.quote, message)
        assert sort_of(SIG, got.fact.value) == Success(BOOL)


COMPILED = compile(TOY)
FIRM_PROVENANCE = st.one_of(st.just(FromSystem("s")), st.builds(Answered, st.just("q"), st.just("a")),
                            st.builds(Volunteered, st.builds(Quoted, st.just("a"))),
                            st.builds(Volunteered, st.builds(Scored, st.floats(0.8, 1))))
FIRM_FACTS = st.lists(st.one_of(
    st.builds(Fact, st.just("daysLate"), st.integers(0, 4).map(IntLit), FIRM_PROVENANCE),
    st.builds(Fact, st.just("wantsRefund"), st.booleans().map(BoolLit), FIRM_PROVENANCE),
), max_size=4).map(lambda fs: make_facts(*fs))


@given(FIRM_FACTS)
def test_e5_without_weak_facts_decide_robustly_is_decide(fs):
    assert decide_robustly(COMPILED, fs) == decide(COMPILED, fs)
