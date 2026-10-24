"""Display phrases: how a fact or an outcome is shown to a policy author, in plain words."""
import json

import jsonschema
import yaml
from conftest import POLICIES
from returns.result import Failure, Success

from policyproof.core.codec import DecodeError, IllTyped, from_yaml, to_yaml
from policyproof.core.syntax import BoolLit, EnumLit, Template, ValuePhrases
from policyproof.core.typecheck import BadDisplay
from policyproof.schema import load

TOY = (POLICIES / "toy.yaml").read_text()
CARRIER = "  carrier: { sort: Carrier, role: system, description: Who delivered the parcel. }\n"
DAYS = "  daysLate: { sort: Int, role: system, description: Days the parcel arrived after the promised date. }\n"
WANTS = "    description: True if the customer wants a refund rather than a voucher.\n"
REFUND = "  refund: { refund: true }\n"


def toy_with(carrier: str = "", days: str = "", wants: str = "", refund: str = "") -> str:
    text = TOY
    if carrier:
        text = text.replace(CARRIER, f"  carrier:\n    sort: Carrier\n    role: system\n"
                                     f"    description: Who delivered the parcel.\n    display: {carrier}\n")
    if days:
        text = text.replace(DAYS, f"  daysLate:\n    sort: Int\n    role: system\n"
                                  f"    description: Days late.\n    display: {days}\n")
    if wants:
        text = text.replace(WANTS, WANTS + f"    display: {wants}\n")
    if refund:
        text = text.replace(REFUND, f"  refund: {{ refund: true, display: {refund} }}\n")
    return text


FULL = toy_with(carrier='{ COURIER: "Came by courier", POST: "Came by post" }', days='"{} days late"',
                wants='{ true: "Asked for a refund", false: "Didn\'t ask for a refund" }', refund='"A refund"')


def var(p, name):
    return next(v for v in p.variables if v.name == name)


def test_display_round_trips():
    p = from_yaml(FULL).unwrap()
    assert var(p, "carrier").display == ValuePhrases(((EnumLit("Carrier", "COURIER"), "Came by courier"),
                                                      (EnumLit("Carrier", "POST"), "Came by post")))
    assert var(p, "daysLate").display == Template("{} days late")
    assert var(p, "wantsRefund").display == ValuePhrases(((BoolLit(True), "Asked for a refund"),
                                                          (BoolLit(False), "Didn't ask for a refund")))
    assert next(o for o in p.outcomes if o.name == "refund").display == "A refund"
    assert var(p, "isLate").display is None
    assert from_yaml(to_yaml(p)) == Success(p)


def bad_display(text: str) -> tuple[str, ...]:
    result = from_yaml(text)
    assert isinstance(result, Failure), result
    err = result.failure()
    assert isinstance(err, IllTyped), err
    return tuple(e.variable for e in err.errors if isinstance(e, BadDisplay))


def test_display_errors_are_sort_errors():
    assert bad_display(toy_with(wants='"{} wants"')) == ("wantsRefund",)            # a template on a Bool
    assert bad_display(toy_with(days='{ 3: "three days" }')) == ("daysLate",)       # a map on an Int
    assert bad_display(toy_with(days='"days late"')) == ("daysLate",)               # no {}
    assert bad_display(toy_with(days='"{} days, {} late"')) == ("daysLate",)        # two {}


def test_unknown_display_keys_are_decode_errors():
    result = from_yaml(toy_with(carrier='{ NOPE: "x" }'))
    assert isinstance(result, Failure)
    err = result.failure()
    assert isinstance(err, DecodeError) and err.path == "variables.carrier.display.NOPE"


def test_outcome_display_needs_text():
    result = from_yaml(toy_with(refund="3"))
    assert isinstance(result, Failure)
    err = result.failure()
    assert isinstance(err, DecodeError) and err.path == "outcomes.refund.display"


def test_schema_accepts_display():
    data = json.loads(json.dumps(yaml.safe_load(FULL)))  # JSON keys are text, as a non-Python tool sees them
    jsonschema.validate(data, load())
