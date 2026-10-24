"""LLMPhraser against a scripted model: a situation's title and a rule as a plain sentence."""
import asyncio

from conftest import load
from returns.result import Failure, Success
from scripted_model import Script

from policyproof.authoring.llm.phraser import LLMPhraser
from policyproof.effects.errors import Malformed

POLICY = load("defects/couriers.yaml")


def test_title_and_sentence():
    s = Script("A courier parcel arrives 3 days late and the customer asks for a refund")
    phraser = LLMPhraser(s.model)
    assert asyncio.run(phraser.title(POLICY, ("Came by courier", "3 days late"))) == Success(
        "A courier parcel arrives 3 days late and the customer asks for a refund")
    assert "Came by courier" in s.instructions()
    s2 = Script("Courier parcels are never refunded.")
    assert asyncio.run(LLMPhraser(s2.model).sentence(POLICY, POLICY.rules[0])) == Success(
        "Courier parcels are never refunded.")
    assert "Who delivered the parcel" in s2.instructions()


def test_an_empty_or_long_title_is_malformed():
    assert isinstance(asyncio.run(LLMPhraser(Script("  ").model).title(POLICY, ("x",))), Failure)
    result = asyncio.run(LLMPhraser(Script(" ".join(["word"] * 30)).model).title(POLICY, ("x",)))
    assert isinstance(result, Failure) and isinstance(result.failure(), Malformed)
