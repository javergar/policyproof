from conftest import load
from returns.pipeline import is_successful

from policyproof.core.solver import compile
from policyproof.core.syntax import BoolLit, EnumLit
from policyproof.core.validate import (
    Conflict,
    ConstraintRule,
    DefinitionToReview,
    DisjointGroups,
    ImpossibleInput,
    NearDuplicate,
    NotTotal,
    UnreachableOutcome,
    UnusedVariable,
    gate,
    severity,
    validate,
)


def report(name: str):
    return validate(compile(load(name)))


def test_the_toy_policy_only_has_reviews(toy):
    assert validate(compile(toy)) == (DefinitionToReview("T1"), ConstraintRule("T6"))
    assert is_successful(gate(compile(toy)))


def test_not_total():
    found = report("defects/not_total.yaml")
    assert NotTotal({"coolingOff": BoolLit(True), "outsideControl": BoolLit(True)}) in found
    assert not is_successful(gate(compile(load("defects/not_total.yaml"))))


def test_bare_assertion_makes_a_value_impossible():
    found = report("defects/bare_assertion.yaml")
    assert ImpossibleInput("itemCategory", EnumLit("ItemCategory", "OTHER")) in found
    assert ConstraintRule("B1") in found


def test_near_duplicate_names_and_disjoint_rules():
    found = report("defects/near_duplicate.yaml")
    assert NearDuplicate("isFinalSale", "finalSale") in found
    assert DisjointGroups((("C1",), ("C2",))) in found


def test_unreachable_outcome():
    assert UnreachableOutcome("credit") in report("defects/unreachable_outcome.yaml")


def test_conflict_skips_the_logical_checks_and_comes_first():
    found = report("defects/conflict.yaml")
    assert found[0] == Conflict(("K1", "K2"))
    assert UnusedVariable("unused") in found
    ranks = [["error", "warning", "review"].index(severity(f)) for f in found]
    assert ranks == sorted(ranks)
