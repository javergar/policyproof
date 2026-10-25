"""The marketing mix example: the optimizer's plan follows the guidelines (proved by the same policy), the questions
and refusals come from the policy, and a guideline that rules out every plan is caught. Z3 only, no model."""
import importlib.util
import json
import sys
from fractions import Fraction
from pathlib import Path

from returns.result import Failure

from policyproof.core.decide import Decided, NeedInfo
from policyproof.core.validate import UnreachableOutcome

HERE = Path(__file__).parent.parent.parent / "examples" / "marketing_mix"
_spec = importlib.util.spec_from_file_location("marketing_mix_plan", HERE / "plan.py")
assert _spec and _spec.loader
plan = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = plan  # dataclasses look their module up
_spec.loader.exec_module(plan)

DATA = plan.load_data(HERE / "planning_data.json")
C = plan.guidelines((HERE / "policy.yaml").read_text()).unwrap()


def best(legal: bool):
    p = plan.optimise(C, DATA, legal=legal)
    assert isinstance(p, plan.Plan), p
    return p


def test_the_best_plan_is_proved_to_follow_every_guideline():
    p = best(legal=False)
    d = plan.prove(C, DATA, p.spend, legal=False)
    assert isinstance(d, Decided) and d.outcome == "go", d
    assert plan.broken(C, DATA, p.spend, legal=False) == ()


def test_without_legal_sign_off_the_plan_buys_no_tv():
    assert all(v == 0 for k, v in best(legal=False).spend.items() if k.endswith("Tv"))


def test_legal_sign_off_is_worth_asking_for():
    without, with_tv = best(legal=False), best(legal=True)
    assert sum(v for k, v in with_tv.spend.items() if k.endswith("Tv")) > 0
    assert with_tv.margin > without.margin
    # the TV plan can't be approved until legal answers, and the policy says what each answer leads to
    d = plan.prove(C, DATA, with_tv.spend, legal=None)
    assert isinstance(d, NeedInfo) and d.var == "legalSignedOff", d
    assert {str(o) for _, o in d.what_if} == {"go", "revise"}


def test_low_stock_skus_get_no_lower_funnel_spend():
    low = [s.key for s in DATA.skus if s.stock_weeks < 2]
    assert low, "the data has a low-stock SKU"
    for p in (best(legal=False), best(legal=True)):
        assert all(p.spend[f"{k}{ch}"] == 0 for k in low for ch in ("Search", "Retail"))


def test_the_launch_gets_its_share_upper_funnel():
    p = best(legal=True)
    launch = next(s.key for s in DATA.skus if s.launching)
    own = sum(p.spend[f"{launch}{ch}"] for ch in plan.CHANNELS)
    upper = p.spend[f"{launch}Tv"] + p.spend[f"{launch}Social"]
    assert own >= Fraction(1, 5) * DATA.budget and upper >= Fraction(2, 5) * own


def test_last_quarters_plan_is_refused_with_the_guidelines_it_breaks():
    d = plan.prove(C, DATA, DATA.last_quarter, legal=True)
    assert isinstance(d, Decided) and d.outcome == "revise", d
    assert plan.broken(C, DATA, DATA.last_quarter, legal=True) == ("G2", "G7")


def test_a_guideline_that_rules_out_every_plan_is_caught():
    gated = plan.guidelines(plan.with_rule((HERE / "policy.yaml").read_text(), plan.FINANCE_G8))
    assert isinstance(gated, Failure) and UnreachableOutcome("go") in gated.failure()
    assert plan.clash(plan.compiled_anyway((HERE / "policy.yaml").read_text(), plan.FINANCE_G8)) == ("G1", "G5", "G8")


def test_the_data_file_is_what_the_policy_expects():
    raw = json.loads((HERE / "planning_data.json").read_text())
    assert {s["key"] for s in raw["skus"]} == {"trail", "aero", "classic"}
    assert set(plan.CHANNELS) == {"Tv", "Social", "Search", "Retail"}
