"""Phrasings: optional example wordings for a variable's values, used only by readers (never by a decision)."""
from dataclasses import replace
from fractions import Fraction

import jsonschema
import pytest
import yaml
from conftest import POLICIES
from returns.result import Failure, Success

from policyproof.core.codec import DecodeError, IllTyped, from_yaml, to_yaml
from policyproof.core.syntax import BoolLit, EnumLit, IntLit, RealLit
from policyproof.core.typecheck import BadPhrasings, SortMismatch, check_policy
from policyproof.schema import load

TOY = (POLICIES / "toy.yaml").read_text()
WANTS = "    description: True if the customer wants a refund rather than a voucher.\n"


def with_phrasings(block: str, after: str = WANTS) -> str:
    return TOY.replace(after, after + block)


def var(p, name):
    return next(v for v in p.variables if v.name == name)


def test_phrasings_decode_per_value():
    p = from_yaml(with_phrasings("    phrasings:\n      true: [money back, a refund]\n"
                                 "      false: [a voucher is fine]\n")).unwrap()
    assert var(p, "wantsRefund").phrasings == ((BoolLit(True), ("money back", "a refund")),
                                               (BoolLit(False), ("a voucher is fine",)))


def test_enum_keys_may_be_qualified():
    text = TOY.replace("carrier: { sort: Carrier, role: system, description: Who delivered the parcel. }",
                       "carrier:\n    sort: Carrier\n    role: system\n    description: Who delivered the parcel.\n"
                       "    phrasings: { Carrier.POST: [by post], COURIER: [a courier] }")
    p = from_yaml(text).unwrap()
    assert var(p, "carrier").phrasings == ((EnumLit("Carrier", "POST"), ("by post",)),
                                           (EnumLit("Carrier", "COURIER"), ("a courier",)))


@pytest.mark.parametrize(("block", "path", "message"), [
    ("    phrasings:\n      maybe: [x]\n", "variables.wantsRefund.phrasings.maybe", "not a Bool value"),
    ("    phrasings:\n      true: []\n", "variables.wantsRefund.phrasings.true", "at least one"),
    ("    phrasings:\n      true: ['  ']\n", "variables.wantsRefund.phrasings.true[0]", "empty"),
    ("    phrasings: [money back]\n", "variables.wantsRefund.phrasings", "expected a map"),
])
def test_bad_phrasings_are_decode_errors(block, path, message):
    got = from_yaml(with_phrasings(block))
    assert isinstance(got, Failure)
    err = got.failure()
    assert isinstance(err, DecodeError) and err.path == path and message in err.message, err


def test_int_and_real_keys():
    weights = (POLICIES / "weights.yaml").read_text().replace(
        "description: Weight in kilograms. }",
        'description: Weight in kilograms., phrasings: { "2.5": [two and a half] } }')
    p = from_yaml(weights).unwrap()
    assert var(p, "kg").phrasings == ((RealLit(Fraction(5, 2)), ("two and a half",)),)
    late = from_yaml(TOY.replace("description: Days the parcel arrived after the promised date. }",
                                 "description: Days the parcel arrived after the promised date.,"
                                 " phrasings: { 3: [three days] } }")).unwrap()
    assert var(late, "daysLate").phrasings == ((IntLit(3), ("three days",)),)


def test_derived_variables_cannot_have_phrasings():
    text = TOY.replace("refund: { sort: Bool, role: derived, description: The customer gets a refund. }",
                       "refund: { sort: Bool, role: derived, description: The customer gets a refund.,"
                       " phrasings: { true: [refunded] } }")
    got = from_yaml(text)
    assert got == Failure(IllTyped((BadPhrasings("refund", "a derived variable can't have phrasings"),)))


def test_check_policy_checks_phrasings_built_in_python():
    p = from_yaml(TOY).unwrap()
    bad = replace(var(p, "wantsRefund"), phrasings=((IntLit(1), ("one",)),))
    got = check_policy(replace(p, variables=tuple(bad if v.name == "wantsRefund" else v for v in p.variables)))
    assert isinstance(got, Failure) and isinstance(got.failure()[0], SortMismatch)
    empty = replace(var(p, "wantsRefund"), phrasings=((BoolLit(True), ()),))
    got = check_policy(replace(p, variables=tuple(empty if v.name == "wantsRefund" else v for v in p.variables)))
    assert got == Failure((BadPhrasings("wantsRefund", "each value needs at least one non-empty phrasing"),))


def test_phrasings_round_trip_and_satisfy_the_schema():
    block = "    phrasings:\n      true: [money back]\n      false: [a voucher is fine]\n"
    p = from_yaml(with_phrasings(block)).unwrap()
    assert from_yaml(to_yaml(p)) == Success(p)
    jsonschema.validate(yaml.safe_load(to_yaml(p)), load())
