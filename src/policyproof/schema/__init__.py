"""JSON Schema (2020-12) for the YAML policy format.

`build()` is the source of truth; `policy.schema.json` is its output, shipped for non-Python tools and checked by a
test. Regenerate with `uv run python -m policyproof.schema`.
"""
import json
from pathlib import Path

PATH = Path(__file__).with_name("policy.schema.json")
EXPR = {"$ref": "#/$defs/expr"}


def _op(name: str, body: object) -> dict[str, object]:
    return {"type": "object", "required": [name], "additionalProperties": False, "properties": {name: body}}


def _nary(name: str) -> dict[str, object]:
    return _op(name, {"type": "array", "minItems": 2, "items": EXPR})


def _binary(name: str) -> dict[str, object]:
    return _op(name, {"type": "array", "minItems": 2, "maxItems": 2, "items": EXPR})


def build() -> dict[str, object]:
    literal_list = {"type": "array", "minItems": 1, "items": {"$ref": "#/$defs/literal"}}
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "urn:policyproof:policy:1",
        "title": "policyproof policy",
        "description": "Enum sorts, typed variables with roles, rules as expression trees, and named outcomes.",
        "type": "object",
        "required": ["policy", "version", "variables", "rules"],
        "additionalProperties": False,
        "properties": {
            "policy": {"type": "string"},
            "version": {"type": "string"},
            "sorts": {"type": "object", "propertyNames": {"$ref": "#/$defs/name"},
                      "additionalProperties": {"type": "array", "minItems": 1, "items": {"type": "string"}}},
            "variables": {"type": "object", "propertyNames": {"$ref": "#/$defs/name"},
                          "additionalProperties": {"$ref": "#/$defs/variable"}},
            "rules": {"type": "array", "items": {"$ref": "#/$defs/rule"}},
            "outcomes": {"type": "object", "additionalProperties": {
                "type": "object", "minProperties": 1, "additionalProperties": {"$ref": "#/$defs/literal"}}},
        },
        "$defs": {
            "name": {"type": "string", "pattern": "^[A-Za-z_][A-Za-z0-9_]*$"},
            "variable": {
                "type": "object", "required": ["sort", "role"], "additionalProperties": False,
                "properties": {"sort": {"type": "string"}, "role": {"enum": ["system", "ask", "derived"]},
                               "description": {"type": "string"}, "question": {"type": "string"},
                               "confirm_volunteered": {"type": "boolean"}},
                "if": {"properties": {"role": {"const": "ask"}}}, "then": {"required": ["question"]},
            },
            "rule": {
                "type": "object", "required": ["id"], "additionalProperties": False,
                "properties": {"id": {"type": "string"}, "source": {"type": "string"}, "explain": {"type": "string"},
                               "when": EXPR, "then": EXPR, "constraint": EXPR,
                               "define": {"type": "object", "required": ["var", "as"], "additionalProperties": False,
                                          "properties": {"var": {"type": "string"}, "as": EXPR}}},
                "oneOf": [{"required": ["when", "then"]}, {"required": ["define"]}, {"required": ["constraint"]}],
            },
            "real": _op("real", {"type": ["string", "integer"]}),
            "literal": {"anyOf": [{"type": "boolean"}, {"type": "integer"}, {"type": "string"},
                                  {"$ref": "#/$defs/real"}]},
            "expr": {"anyOf": [
                {"type": "boolean"}, {"type": "integer"}, {"type": "string"}, {"$ref": "#/$defs/real"},
                _op("not", EXPR), _nary("and"), _nary("or"), _binary("implies"), _binary("iff"),
                *[_binary(c) for c in ("eq", "ne", "lt", "le", "gt", "ge", "sub")], _nary("add"), _nary("mul"),
                _op("in", {"type": "array", "minItems": 2, "maxItems": 2, "prefixItems": [EXPR, literal_list]}),
            ]},
        },
    }


def load() -> dict[str, object]:
    return json.loads(PATH.read_text())


def write() -> None:
    PATH.write_text(json.dumps(build(), indent=2) + "\n")
