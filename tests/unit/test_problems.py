"""Every problem in a policy, each with its own minimal example customer (the studio's problem list)."""
from conftest import load

from policyproof.core import problems as problems_module
from policyproof.core.problems import (
    Clash,
    Gap,
    GaveUp,
    OutrightConflict,
    Problems,
    Says,
    groups,
    problems,
    still_a_problem,
)
from policyproof.core.solver import Unknown, compile
from policyproof.core.syntax import BoolLit, EnumLit, IntLit

T, F = BoolLit(True), BoolLit(False)
COURIER = EnumLit("Carrier", "COURIER")


def clashes(found):
    return [f for f in found if isinstance(f, Clash)]


def test_three_rules_clash_with_no_pair_at_fault():
    found = problems(compile(load("defects/not_total.yaml")))
    [clash] = clashes(found.found)
    assert clash.rules == ("R4", "R8", "R10")
    assert clash.customer == (("coolingOff", T), ("outsideControl", T))
    assert clash.says == (Says("R4", (("credit", T),)), Says("R8", (("refund", T),)), Says("R10", ()))


def test_clashes_are_distinct_by_rule_set():
    found = clashes(problems(compile(load("defects/clashes.yaml"))).found)
    assert {c.rules for c in found} == {("C4", "C5"), ("C4", "C6"), ("C7", "C8")}
    lost = next(c for c in found if c.rules == ("C4", "C6"))
    assert lost.customer == (("carrier", COURIER), ("lost", T))
    assert lost.says == (Says("C4", (("refund", F),)), Says("C6", (("refund", T),)))


def test_an_integer_input_gives_one_clash_per_rule_set():
    result = problems(compile(load("defects/clashes.yaml")))
    late = [c for c in clashes(result.found) if c.rules == ("C4", "C5")]
    assert len(late) == 1
    customer = dict(late[0].customer)
    assert customer.keys() == {"carrier", "daysLate", "asked"}
    assert customer["asked"] == T and customer["carrier"] == COURIER
    days = customer["daysLate"]
    assert isinstance(days, IntLit) and days.value > 0
    assert result.complete


def test_a_witness_extends_its_customer():
    for c in clashes(problems(compile(load("defects/clashes.yaml"))).found):
        assert set(c.customer) <= set(c.witness)


def test_a_gap_has_a_minimal_customer():
    assert problems(compile(load("defects/gap.yaml"))) == Problems(
        (Gap((("late", F),), (("late", F),), ("G1",)),), True)


def test_an_outright_conflict_stops_there():
    assert problems(compile(load("defects/conflict.yaml"))) == Problems((OutrightConflict(("K1", "K2")),), True)


def test_the_toy_policy_has_no_problems(toy):
    assert problems(compile(toy)) == Problems((), True)


def test_solver_giving_up_is_reported(monkeypatch):
    monkeypatch.setattr(problems_module, "totality", lambda *a, **k: Unknown("timeout"))
    result = problems(compile(load("defects/clashes.yaml")))
    assert GaveUp("clashes", "timeout") in result.found
    assert not result.complete


def test_the_cap_marks_the_list_incomplete():
    result = problems(compile(load("defects/clashes.yaml")), cap=1)
    assert len(clashes(result.found)) == 1
    assert not result.complete


def test_groups_follow_shared_rules():
    found = clashes(problems(compile(load("defects/clashes.yaml"))).found)
    gs = groups(found)
    by_rules = [tuple(found[i].rules for i in g) for g in gs]
    assert sorted(len(g) for g in gs) == [1, 2]
    assert any(set(g) == {("C4", "C5"), ("C4", "C6")} for g in by_rules)
    assert sorted(i for g in gs for i in g) == list(range(len(found)))


def test_still_a_problem_holds_where_found():
    for name in ("defects/clashes.yaml", "defects/gap.yaml", "defects/not_total.yaml"):
        c = compile(load(name))
        for f in problems(c).found:
            assert isinstance(f, Clash | Gap)
            assert still_a_problem(c, f)
