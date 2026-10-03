from dataclasses import FrozenInstanceError
from fractions import Fraction

import pytest

from policyproof.core.syntax import (
    BOOL,
    And,
    Ask,
    BoolLit,
    Cmp,
    EnumLit,
    IntLit,
    RealLit,
    Var,
    Variable,
    When,
    rule_id,
)


def test_literals_are_tagged_so_true_is_not_one():
    assert BoolLit(True) != IntLit(1)
    assert IntLit(3) != RealLit(Fraction(3))
    assert EnumLit("Fare", "LITE") == EnumLit("Fare", "LITE")


def test_nodes_are_immutable_and_hashable():
    e = And((Var("a"), Cmp("ge", Var("n"), IntLit(3))))
    with pytest.raises(FrozenInstanceError):
        e.args = ()  # ty: ignore[invalid-assignment]  (ty also rejects this statically)
    assert {e: 1}[And((Var("a"), Cmp("ge", Var("n"), IntLit(3))))] == 1


def test_rule_and_variable_fields():
    r = When("R3", Var("a"), Var("b"), source="rule 3")
    assert rule_id(r) == "R3" and r.explain is None
    v = Variable("wantsToTravel", BOOL, Ask("Do you still want to take this trip?"), "…")
    assert isinstance(v.role, Ask) and v.role.confirm_volunteered
