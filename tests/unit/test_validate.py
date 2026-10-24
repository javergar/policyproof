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
    Undecided,
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


def _compiled(text: str, **kw):
    from policyproof.core.codec import from_yaml
    return compile(from_yaml(text).unwrap(), **kw)


RELATED = """policy: t
version: "1"
variables:
  member: { sort: Bool, role: system }
  wants: { sort: Bool, role: ask, question: "Want it?" }
  refund: { sort: Bool, role: derived }
rules:
  - { id: R1, when: member, then: wants }
  - { id: R2, when: wants, then: refund }
outcomes:
  refund: { refund: true }
"""


def test_rules_between_inputs_are_reported_for_review():
    from policyproof.core.validate import InputsRelated
    found = validate(_compiled(RELATED))
    assert InputsRelated("R1") in found and severity(InputsRelated("R1")) == "review"


HARD = """policy: t
version: "1"
variables:
  b: { sort: Bool, role: system }
  x: { sort: Int, role: system }
  y: { sort: Int, role: system }
  z: { sort: Int, role: system }
rules:
  - id: H1
    when: b
    then:
      and: [{ gt: [x, 0] }, { gt: [y, 0] }, { gt: [z, 0] },
            { eq: [{ add: [{ mul: [x, x, x] }, { mul: [y, y, y] }] }, { mul: [z, z, z] }] }]
"""


def test_a_check_the_solver_gives_up_on_is_an_error_not_a_pass():
    from policyproof.core.validate import SolverGaveUp
    found = validate(_compiled(HARD, timeout_ms=300))
    assert any(isinstance(f, SolverGaveUp) and f.check.startswith("impossible input b") for f in found)


def test_gap_is_a_warning():
    found = report("defects/gap.yaml")
    assert Undecided({"late": BoolLit(False)}) in found
    assert severity(Undecided({"late": BoolLit(False)})) == "warning"
    assert is_successful(gate(compile(load("defects/gap.yaml"))))
