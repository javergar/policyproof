from conftest import load

from policyproof.core.solver import compile
from policyproof.core.validate import (
    ConstraintRule,
    DefinitionToReview,
    InputsRelated,
    OverlappingOutcomes,
    validate,
)


def test_flight_disruption_has_only_review_findings():
    assert validate(compile(load("flight_disruption.yaml"))) == (
        OverlappingOutcomes("free_rebooking", "no_refund_or_credit"),
        DefinitionToReview("R1"), DefinitionToReview("R2"), DefinitionToReview("R8def"), ConstraintRule("RANGE1"))


def test_retail_refund_can_give_a_refund_and_store_credit_at_once():
    """A real gap in the lab's policy: nothing says a refund and store credit exclude each other."""
    assert validate(compile(load("retail_refund.yaml"))) == (
        OverlappingOutcomes("refund", "store_credit"), OverlappingOutcomes("store_credit", "no_refund"),
        ConstraintRule("V8UWX090HX0T"), InputsRelated("ABM61UCQIATH"))
