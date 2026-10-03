import jsonschema
import pytest
import yaml

from policyproof import schema
from policyproof.core.codec import to_yaml


def test_shipped_schema_matches_the_builder():
    assert schema.load() == schema.build()


def test_toy_validates_against_the_schema(toy):
    jsonschema.Draft202012Validator(schema.load()).validate(yaml.safe_load(to_yaml(toy)))


@pytest.mark.parametrize("bad", [
    {"policy": "p", "version": "1", "variables": {}, "rules": [{"id": "R1", "when": True}]},
    {"policy": "p", "version": "1", "variables": {}, "rules": [{"id": "R1", "when": {"and": [True]}, "then": True}]},
    {"policy": "p", "version": "1", "variables": {"x": {"sort": "Bool", "role": "ask"}}, "rules": []},
    {"policy": "p", "version": 1, "variables": {}, "rules": []},
])
def test_schema_rejects_malformed_policies(bad):
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.Draft202012Validator(schema.load()).validate(bad)
