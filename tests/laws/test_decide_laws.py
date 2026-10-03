"""L8 monotonicity, L9 the merge semilattice, L10 questions make progress (on the toy policy)."""
from conftest import load
from hypothesis import given
from hypothesis import strategies as st

from policyproof.core.decide import Contradiction, Decided, NeedInfo, decide
from policyproof.core.facts import Answered, Fact, FromSystem, Volunteered, facts, merge
from policyproof.core.solver import compile
from policyproof.core.syntax import BoolLit, EnumLit, IntLit

TOY = compile(load("toy.yaml"))
VALUES = {"daysLate": st.integers(0, 4).map(IntLit),
          "carrier": st.sampled_from(["POST", "COURIER"]).map(lambda v: EnumLit("Carrier", v)),
          "wantsRefund": st.booleans().map(BoolLit)}
SOURCE = {"daysLate": FromSystem("tracking"), "carrier": FromSystem("tracking"), "wantsRefund": Answered("q", "a")}
WORLDS = st.fixed_dictionaries(VALUES)


def firm(world: dict, names) -> list[Fact]:
    return [Fact(n, world[n], SOURCE[n]) for n in names]


@given(WORLDS, st.sets(st.sampled_from(sorted(VALUES))), st.sets(st.sampled_from(sorted(VALUES))))
def test_l8_a_decision_survives_more_facts(world, f_names, more):
    """The toy's outcomes are mutually exclusive (no OverlappingOutcomes finding), which this law needs."""
    before = decide(TOY, facts(*firm(world, f_names)))
    after = decide(TOY, facts(*firm(world, f_names | more)))
    if isinstance(before, Decided) and not isinstance(after, Contradiction):
        assert isinstance(after, Decided) and after.outcome == before.outcome


PROVENANCE = st.one_of(st.just(FromSystem("s")), st.builds(Answered, st.sampled_from("qr"), st.sampled_from("ab")),
                       st.builds(Volunteered, st.sampled_from("ab")))
FACT_SETS = st.lists(st.builds(Fact, st.sampled_from("xyz"), st.integers(0, 2).map(IntLit), PROVENANCE),
                     max_size=5).map(lambda fs: facts(*fs))


@given(FACT_SETS, FACT_SETS, FACT_SETS)
def test_l9_merge_is_a_semilattice(a, b, c):
    assert merge(merge(a, b), c) == merge(a, merge(b, c))
    assert merge(a, b) == merge(b, a)
    assert merge(a, a) == a


@given(WORLDS)
def test_l10_answering_the_questions_always_ends(world):
    known = firm(world, ["daysLate", "carrier"])
    asked: list[str] = []
    for _ in range(3):
        d = decide(TOY, facts(*known))
        if not isinstance(d, NeedInfo):
            break
        assert d.var not in asked, "the same question twice"
        asked.append(d.var)
        known.append(Fact(d.var, world[d.var], SOURCE[d.var]))
    assert isinstance(d, Decided)
