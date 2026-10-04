"""E1: the pydantic models of the expression grammar (what the LLM is asked to fill) agree with the published JSON
Schema and with the codec: every expression's encoding validates in both and round-trips unchanged."""
import jsonschema
from hypothesis import given
from hypothesis import strategies as st
from pydantic import TypeAdapter, ValidationError
from strategies import exprs

from policyproof.core.codec import encode_expr
from policyproof.core.syntax import BOOL, INT, REAL
from policyproof.effects.llm.exprmodel import Expr
from policyproof.schema import build

ADAPTER: TypeAdapter = TypeAdapter(Expr)
SCHEMA = {"$schema": "https://json-schema.org/draft/2020-12/schema", "$defs": build()["$defs"], "$ref": "#/$defs/expr"}
ANY = st.one_of(exprs(BOOL), exprs(INT), exprs(REAL))


@given(ANY)
def test_e1_every_expression_validates_in_both_and_round_trips(e):
    data = encode_expr(e)
    jsonschema.validate(data, SCHEMA)
    assert ADAPTER.dump_python(ADAPTER.validate_python(data), mode="json", by_alias=True) == data


def test_e1_both_reject_the_same_malformed_shapes():
    for bad in [{"and": ["p"]}, {"not": "p", "and": ["p", "q"]}, {"implies": ["p", "q", "r"]}, {"xor": ["p", "q"]},
                {"in": ["c"]}, {"real": 2.5}, 2.5, None, []]:
        try:
            ADAPTER.validate_python(bad)
            raise AssertionError(f"model accepted {bad!r}")
        except ValidationError:
            pass
        assert not jsonschema.Draft202012Validator(SCHEMA).is_valid(bad), bad
