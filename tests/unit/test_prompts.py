"""Snapshots of every prompt for the toy policy. After an intended change: PP_UPDATE_SNAPSHOTS=1 uv run pytest."""
import json
import os
from pathlib import Path

from conftest import POLICIES, load
from returns.result import Success

from policyproof.core.check import Problem
from policyproof.core.codec import decode_expr, from_data, from_yaml
from policyproof.core.syntax import BOOL
from policyproof.core.typecheck import signature, sort_of
from policyproof.effects.llm.prompts import answer_prompt, claims_prompt, examples, facts_prompt, rewrite_prompt

SNAPSHOT = Path(__file__).parent.parent / "snapshots" / "toy_prompts.txt"


def test_prompts_match_the_snapshot(toy):
    text = "\n\n=====\n\n".join([
        answer_prompt(toy, "wantsRefund"), facts_prompt(toy), claims_prompt(toy),
        rewrite_prompt((Problem("claims_hold", '"a voucher" contradicts the policy and the facts.'),), "Be brief."),
    ]) + "\n"
    if os.environ.get("PP_UPDATE_SNAPSHOTS"):
        SNAPSHOT.write_text(text)
    assert text == SNAPSHOT.read_text()


def test_the_facts_prompt_never_offers_derived_variables(toy):
    assert "- refund" not in facts_prompt(toy) and "- wantsRefund" in facts_prompt(toy)


def test_examples_use_the_policys_own_names(toy):
    assert examples(toy) == ('{"ge": ["daysLate", 2]}, {"eq": ["carrier", "POST"]}, '
                             '"wantsRefund", {"not": "wantsRefund"}')


def test_every_example_is_a_well_typed_statement(toy):
    for p in (toy, load("weights.yaml")):
        sig = signature(p)
        for data in json.loads(f"[{examples(p)}]"):
            e = from_data(data).bind(lambda t, sig=sig: decode_expr(sig, t)).unwrap()
            assert sort_of(sig, e) == Success(BOOL), data


PHRASED = (POLICIES / "toy.yaml").read_text().replace(
    "    description: True if the customer wants a refund rather than a voucher.\n",
    "    description: True if the customer wants a refund rather than a voucher.\n"
    "    phrasings:\n      true: [money back, a refund]\n      false: [a voucher is fine]\n")
SAID = 'said as: true: "money back", "a refund"; false: "a voucher is fine"'


def test_phrasings_reach_the_answer_and_facts_prompts_only():
    p = from_yaml(PHRASED).unwrap()
    assert SAID in answer_prompt(p, "wantsRefund")
    assert f"- wantsRefund (true or false): True if the customer wants a refund rather than a voucher.\n  {SAID}" in (
        facts_prompt(p))
    assert "said as" not in claims_prompt(p)
