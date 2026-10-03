import json

import pytest
from returns.pipeline import is_successful
from returns.result import Failure

from policyproof.core.codec import DecodeError, IllTyped, Pos, decode, encode, from_yaml, to_yaml
from policyproof.core.syntax import INT, And, Cmp, Define, EnumLit, IntLit, Not, Or, Var, When
from policyproof.core.typecheck import SortMismatch

TOY_HEAD = """policy: t
version: "1"
sorts: { Carrier: [POST, COURIER], Mode: [POST, AIR] }
variables:
  n: { sort: Int, role: system }
  b: { sort: Bool, role: derived }
  c: { sort: Carrier, role: system }
rules:
"""


def failure(text: str) -> DecodeError | IllTyped:
    result = from_yaml(text)
    assert not is_successful(result), result
    return result.failure()


def test_decodes_the_toy_policy(toy):
    assert toy.name == "toy-delivery" and [r.id for r in toy.rules] == ["T1", "T2", "T3", "T4", "T5", "T6"]
    t1, t2, t4 = toy.rules[0], toy.rules[1], toy.rules[3]
    assert isinstance(t1, Define) and t1.var == "isLate" and t1.source == "clause 1"
    assert t1.as_ == Or((Cmp("ge", Var("daysLate"), IntLit(2)),
                         And((Cmp("eq", Var("carrier"), EnumLit("Carrier", "COURIER")),
                              Cmp("ge", Var("daysLate"), IntLit(1))))))
    assert t2 == When("T2", And((Var("isLate"), Var("wantsRefund"))), Var("refund"), "clause 2")
    assert isinstance(t4, When) and t4.then == And((Not(Var("refund")), Not(Var("voucher"))))
    assert [o.name for o in toy.outcomes] == ["refund", "voucher", "nothing"]


def test_toy_round_trips_through_yaml_and_json(toy):
    assert from_yaml(to_yaml(toy)).unwrap() == toy
    assert decode(json.loads(json.dumps(encode(toy)))).unwrap() == toy


@pytest.mark.parametrize(("rule", "path", "message"), [
    ("  - { id: R1, when: nope, then: b }", "rules[0].when", "unknown name 'nope'"),
    ("  - { id: R1, when: POST, then: b }", "rules[0].when", "'POST' is a value of Carrier, Mode; qualify it"),
    ("  - { id: R1, when: { ge: [n, 2.5] }, then: b }", "rules[0].when.ge[1]", "write decimals as"),
    ("  - { id: R1, when: { ge: [n] }, then: b }", "rules[0].when.ge", "expected two operands, found 1"),
    ("  - { id: R1, when: { and: [b] }, then: b }", "rules[0].when.and", "expected two or more operands"),
    ("  - { id: R1, when: { xor: [b, b] }, then: b }", "rules[0].when.xor", "unknown operator 'xor'"),
    ("  - { id: R1, when: { not: b, and: [b, b] }, then: b }", "rules[0].when", "exactly one key, found 2"),
    ("  - { id: R1, when: b }", "rules[0]", "missing required key 'then'"),
    ("  - { id: R1, when: b, then: b, constraint: b }", "rules[0]", "exactly one of"),
    ("  - { id: R1, when: b, then: b, colour: red }", "rules[0].colour", "unknown key 'colour'"),
])
def test_decode_errors_name_the_path_and_line(rule, path, message):
    err = failure(TOY_HEAD + rule + "\n")
    assert isinstance(err, DecodeError)
    assert err.path == path and message in err.message
    assert err.pos is not None and err.pos.line == 9


def test_qualified_enum_values_resolve():
    p = from_yaml(TOY_HEAD + "  - { id: R1, when: { eq: [c, Carrier.POST] }, then: b }\n").unwrap()
    assert p.rules[0] == When("R1", Cmp("eq", Var("c"), EnumLit("Carrier", "POST")), Var("b"))


def test_sort_errors_come_back_as_ill_typed():
    err = failure(TOY_HEAD + "  - { id: R1, when: n, then: b }\n")
    assert err == IllTyped((SortMismatch("Bool", INT, "R1"),))


def test_invalid_yaml_reports_the_position():
    err = failure("policy: [unclosed\n")
    assert isinstance(err, DecodeError) and "invalid YAML" in err.message and err.pos == Pos(2, 1)


def test_version_must_be_text():
    err = failure(TOY_HEAD.replace('version: "1"', "version: 1.0") + "  - { id: R1, when: b, then: b }\n")
    assert isinstance(err, DecodeError) and err.path == "version" and "quote numbers" in err.message


def test_failure_is_a_value_not_an_exception():
    assert isinstance(from_yaml(""), Failure)


def test_yaml_booleans_as_enum_values_ask_for_quotes():
    err = failure('policy: t\nversion: "1"\nsorts: { Answer: [YES, NO] }\nvariables: {}\nrules: []\n')
    assert isinstance(err, DecodeError) and err.path == "sorts.Answer[0]" and 'quote it, e.g. "YES"' in err.message
    quoted = from_yaml('policy: t\nversion: "1"\nsorts: { Answer: ["YES", "NO"] }\nvariables: {}\nrules: []\n')
    assert quoted.unwrap().sorts[0].values == ("YES", "NO")


def test_an_unquoted_comma_in_a_flow_map_is_a_positioned_error_not_a_crash():
    comma = "n: { sort: Int, role: system, description: late, or early }"
    head = TOY_HEAD.replace("n: { sort: Int, role: system }", comma)
    err = failure(head + "  - { id: R1, when: b, then: b }\n")
    assert isinstance(err, DecodeError) and err.pos == Pos(5, 6)
    assert err.message.startswith("unknown key 'or early' (a comma inside { } starts a new key")
