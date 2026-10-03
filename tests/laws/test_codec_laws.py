"""L1 and L2: the codecs round-trip, and every encoded policy satisfies the published schema."""
import jsonschema
import yaml
from hypothesis import given
from returns.result import Success
from strategies import SIG, exprs, policies

from policyproof import schema
from policyproof.core.codec import decode_expr, encode, encode_expr, from_data, from_yaml, to_yaml
from policyproof.core.syntax import BOOL, INT, REAL
from policyproof.core.typecheck import check_policy

VALIDATOR = jsonschema.Draft202012Validator(schema.load())


@given(exprs(BOOL) | exprs(INT) | exprs(REAL))
def test_l1_expressions_round_trip(e):
    assert from_data(encode_expr(e)).bind(lambda t: decode_expr(SIG, t)) == Success(e)


@given(policies())
def test_l2_policies_round_trip_through_yaml(p):
    checked = check_policy(p).unwrap()
    assert from_yaml(to_yaml(checked)) == Success(checked)


@given(policies())
def test_l2_encoded_policies_satisfy_the_schema(p):
    VALIDATOR.validate(yaml.safe_load(to_yaml(p)))
    VALIDATOR.validate(encode(p))
