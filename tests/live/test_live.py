"""Live runs against real models. Not part of the default run or CI: `uv run pytest -m live`.

Bedrock: set PP_BEDROCK_MODEL (an inference profile ID, e.g. au.anthropic.claude-haiku-4-5-20251001-v1:0) and the usual
AWS credentials and region. Jev: set TYPESAFE_API_KEY. Each test is skipped when its credentials aren't there.
"""
import asyncio
import os

import boto3
import pytest
from returns.result import Success

from policyproof.core.decide import Decided, NeedInfo, decide
from policyproof.core.facts import Answered, Fact, FromSystem, facts
from policyproof.core.solver import compile
from policyproof.core.syntax import BoolLit, IntLit
from policyproof.effects.pipeline import Conversation, Readers, guard_reply, read_turn

pytestmark = pytest.mark.live
LATE = Fact("daysLate", IntLit(3), FromSystem("tracking"))
needs_bedrock = pytest.mark.skipif(not os.environ.get("PP_BEDROCK_MODEL") or boto3.Session().get_credentials() is None,
                                   reason="set PP_BEDROCK_MODEL and AWS credentials")
needs_jev = pytest.mark.skipif(not os.environ.get("TYPESAFE_API_KEY"), reason="set TYPESAFE_API_KEY")


def llm():
    from pydantic_ai.models.bedrock import BedrockConverseModel

    from policyproof.effects.llm.readers import LLMReaders
    return LLMReaders(BedrockConverseModel(os.environ["PP_BEDROCK_MODEL"]))


def jev():
    from pydantic_ai.models.typesafe import TypeSafeModel

    from policyproof.effects.jev.readers import JevReaders
    return JevReaders(TypeSafeModel("jev-1.13.0"))


def asked(c) -> Conversation:
    pending = decide(c, facts(LATE))
    assert isinstance(pending, NeedInfo)
    return Conversation(facts(LATE), pending, frozenset())


@needs_bedrock
def test_bedrock_reads_an_answer_into_a_decision(toy):
    c, r = compile(toy), llm()
    turn = asyncio.run(read_turn(c, asked(c), "Yes, I'd like my money back please.", Readers(r, r))).unwrap()
    assert isinstance(turn.decision, Decided) and turn.decision.outcome == "refund"


@needs_bedrock
def test_bedrock_passes_a_correct_reply_and_stops_a_wrong_one(toy):
    c, r = compile(toy), llm()
    fs = facts(LATE, Fact("wantsRefund", BoolLit(True), Answered("Would you like your money back?", "yes")))
    d = decide(c, fs)
    ok = asyncio.run(guard_reply(c, fs, d, "Your parcel was 3 days late, so you'll get a refund.", r, r))
    assert not ok.fell_back, ok
    wrong = asyncio.run(guard_reply(c, fs, d, "Your parcel was late, so you'll get a voucher.", r, r))
    assert wrong.attempts == 2  # the wrong draft never goes out as written
    assert wrong.fell_back or (wrong.result is not None and wrong.result.passed)


@needs_jev
def test_jev_reads_facts_and_an_answer(toy):
    c, r = compile(toy), jev()
    found = asyncio.run(r.read_facts(c.policy, "It came by courier and I want my money back.")).unwrap()
    assert {(f.var, f.value) for f in found} >= {("carrier", "COURIER")}
    assert isinstance(asyncio.run(r.read_answer(c.policy, "wantsRefund", "Yes please, money back.")), Success)
