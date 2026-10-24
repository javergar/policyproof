"""The API's shapes: one JSON Schema, generated from `studio.wire`, that every reply meets."""
import json

import jsonschema
from returns.result import Failure, Success

from policyproof.studio import wire as w
from policyproof.studio.schema import SCHEMA, api_schema, dump, parse, schema_text

SENTENCE = w.SentenceView("s1", "Courier parcels are never refunded.", 1, "open", None)
DOC = w.DocView("couriers.md", (w.SectionView(2, "Couriers", (SENTENCE,)),), 4)
ITEM = w.Item("clash:C4+C5", "clash", "error", "A late courier parcel", ("Courier",), "Two rules…",
              (w.Verdict("Rule 1", SENTENCE.text, "No refund", "no"),), None, "What should this customer get?",
              (w.Option("A refund", w.Choose("refund")), w.Option("Depends", w.Describe("On what?", "It depends: ")),
               w.Option("A person decides", w.Dismiss(None))), ("s1",), ("C4: carrier = COURIER → ¬refund",), False,
              None)
STATE = w.SessionView("couriers.md", DOC, (ITEM,), (), 1, 0, (w.ExampleView("e", ("Courier",), "A refund"),),
                      w.Banner(("x",), (), ("Rule 1",)), False, True, False, False, 3)
PROPOSAL = w.ProposalView("p1", (w.Change("replace", "Couriers", "a", "b"),), (w.Check("ok", "Fixes it."),),
                          ("The agent will now ask customers: Was it insured?",),
                          (w.Switch("insured", "Was it insured?", "ask"),), False, 1)
REPLIES = (w.StateReply(STATE), w.ProposalReply(PROPOSAL),
           w.ReextractReply(w.ReextractView("r1", (w.RuleDiff("a", "Couriers", ("x",), ("y",), True, "mine"),))),
           w.OutsideReply(True), w.StartReply("/tmp", False), w.ErrorReply("no"))


def reply_schema():
    return {"$defs": api_schema()["$defs"], "$ref": "#/$defs/Reply"}


def test_the_committed_schema_is_current():
    assert SCHEMA.read_text() == schema_text(), "run: uv run python -m policyproof.studio.schema"


def test_every_reply_validates_against_the_schema():
    schema = reply_schema()
    for r in REPLIES:
        jsonschema.validate(json.loads(dump(r)), schema)


def test_a_reply_missing_a_field_does_not_validate():
    data = json.loads(dump(w.StateReply(STATE)))
    del data["state"]["version"]
    try:
        jsonschema.validate(data, reply_schema())
    except jsonschema.ValidationError:
        return
    raise AssertionError("a reply without version validated")


def test_every_property_is_required():
    for name, d in api_schema()["$defs"].items():
        if "properties" in d:
            assert set(d["required"]) == set(d["properties"]), name


def test_requests_parse():
    got = parse(w.AnswerRequest, b'{"key": "k", "option": 1, "text": ""}')
    assert got == Success(w.AnswerRequest("k", 1, ""))
    assert parse(w.ResolveRequest, b'{"reextract": "r", "keep": ["mine", "new"]}') == Success(
        w.ResolveRequest("r", ("mine", "new")))


def test_a_bad_request_is_a_failure():
    assert isinstance(parse(w.AnswerRequest, b'{"key": "k"}'), Failure)
    assert isinstance(parse(w.ResolveRequest, b'{"reextract": "r", "keep": ["maybe"]}'), Failure)
    assert isinstance(parse(w.AnswerRequest, b'not json'), Failure)
