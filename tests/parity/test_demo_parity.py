"""Parity with the AgentCore demo's decision core (~/code/agentcore-disruption-demo/decision/core.py).

For every demo booking and every way the customer can answer, policyproof must reach the same decision or ask the
same question as the demo. Skipped when the demo isn't checked out next to this repo.
"""
import importlib
import sys
from pathlib import Path

import pytest
from conftest import load

from policyproof.core.decide import Contradiction, Decided, Escalate, NeedInfo, decide
from policyproof.core.facts import Answered, Fact, FromSystem, Volunteered, facts
from policyproof.core.solver import compile
from policyproof.core.syntax import BoolLit, BoolSort, EnumLit, EnumSort, IntLit, IntSort, Lit, Sort

DEMO = Path.home() / "code" / "agentcore-disruption-demo"
pytestmark = pytest.mark.skipif(not (DEMO / "decision" / "core.py").exists(), reason="the demo is not checked out")

ANSWERS = [("none", None), ("answered yes", ("answer", True)), ("answered no", ("answer", False)),
           ("said yes in passing", ("volunteered", True)), ("said no in passing", ("volunteered", False))]


def to_lit(sort: Sort, value: object) -> Lit:
    match sort:
        case BoolSort():
            return BoolLit(bool(value))
        case IntSort():
            return IntLit(int(value))  # ty: ignore[invalid-argument-type] - demo data are ints here
        case EnumSort(name, _):
            return EnumLit(name, str(value))
        case _:
            raise AssertionError(sort)


@pytest.fixture(scope="module")
def demo():
    sys.path.insert(0, str(DEMO / "decision"))  # the demo's modules are flat: `core`, `bookings`
    core, bookings = importlib.import_module("core"), importlib.import_module("bookings")
    return core, bookings, core.Policy.load(DEMO / "policy")


@pytest.mark.parametrize(("label", "answer"), ANSWERS)
@pytest.mark.parametrize("ref", ["K7PQ2M", "R3VN8D", "T4XB9R", "H2LW6C"])
def test_same_decision_as_the_demo(demo, ref, label, answer):
    core, bookings, demo_policy = demo
    policy = load("flight_disruption.yaml")
    sorts = {v.name: v.sort for v in policy.variables}
    system = bookings.system_facts(ref)
    known = [Fact(n, to_lit(sorts[n], v), FromSystem("demo systems")) for n, v in system.items()]
    customer, asked = {}, ()
    if answer is not None:
        how, value = answer
        customer = {"wantsToTravel": value}
        asked = ("wantsToTravel",) if how == "answer" else ()
        provenance = Answered("Do you still want to take this trip?", "...") if how == "answer" else Volunteered("...")
        known.append(Fact("wantsToTravel", BoolLit(value), provenance))

    theirs = core.decide(demo_policy, system, customer, asked)
    ours = decide(compile(policy), facts(*known))

    match ours:
        case Decided(outcome):
            assert theirs["status"] == "decided" and theirs["verdict"] == outcome
        case NeedInfo(var):
            assert theirs["status"] == "need_info" and theirs["variable"] == var
        case Contradiction():
            assert theirs["status"] == "contradiction"
        case Escalate():
            assert theirs["status"] == "escalate"
        case _:
            raise AssertionError(ours)
