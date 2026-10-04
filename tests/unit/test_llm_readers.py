"""LLMReaders against pydantic-ai's FunctionModel: scripted model responses, no network."""
import asyncio
import json

from pydantic_ai.exceptions import ContentFilterError, ModelHTTPError
from pydantic_ai.messages import ModelMessage, ModelRequest, ModelResponse, RetryPromptPart, TextPart, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from returns.result import Failure, Success

from policyproof.core.check import Problem
from policyproof.core.facts import Quoted
from policyproof.effects.errors import Malformed, Refused, Unavailable
from policyproof.effects.llm.readers import LLMReaders
from policyproof.effects.ports import (
    AnswerReader,
    ClaimReader,
    FactReader,
    NotAnswered,
    RawClaim,
    RawFact,
    Rewriter,
    Said,
    Unclear,
)


class Script:
    """A FunctionModel that returns the scripted outputs in order (the last repeats) and records each request."""

    def __init__(self, *outputs: object):
        self.outputs, self.requests, self.infos = outputs, [], []
        self.model = FunctionModel(self.respond)

    def respond(self, messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        self.requests.append(messages)
        self.infos.append(info)
        out = self.outputs[min(len(self.requests), len(self.outputs)) - 1]
        if isinstance(out, Exception):
            raise out
        if isinstance(out, str):
            return ModelResponse(parts=[TextPart(out)])
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, json.dumps(out))])

    def retry_prompts(self) -> list[str]:
        return [str(p.content) for m in self.requests[-1] if isinstance(m, ModelRequest) for p in m.parts
                if isinstance(p, RetryPromptPart)]


MSG = "Yes, money back please. It came by courier."


def answer(script, toy, message=MSG):
    return asyncio.run(LLMReaders(script.model).read_answer(toy, "wantsRefund", message))


def test_an_answer_is_read(toy):
    s = Script({"status": "answered", "value": True, "quote": "money back"})
    assert answer(s, toy) == Success(Said(True, "money back"))
    assert "Would you like your money back?" in s.infos[0].instructions


def test_an_answer_the_guard_rejects_is_retried_once(toy):
    s = Script({"status": "answered", "value": True, "quote": "refund me"},
               {"status": "answered", "value": True, "quote": "money back"})
    assert answer(s, toy) == Success(Said(True, "money back"))
    assert len(s.requests) == 2 and "quote not in message" in s.retry_prompts()[0]


def test_an_answer_rejected_twice_is_unclear_not_an_error(toy):
    s = Script({"status": "answered", "value": False, "quote": "money back"})
    got = answer(s, toy)
    assert isinstance(got.unwrap(), Unclear) and len(s.requests) == 2


def test_unclear_and_unanswered_are_reported(toy):
    assert answer(Script({"status": "unclear", "reason": "hedged"}), toy) == Success(Unclear("hedged"))
    assert answer(Script({"status": "not_answered"}), toy) == Success(NotAnswered())


def test_facts_are_read_and_bad_ones_retried(toy):
    good = {"facts": [{"var": "carrier", "value": "COURIER", "quote": "by courier"}]}
    s = Script({"facts": [{"var": "refund", "value": True, "quote": "money back"}]}, good)
    got = asyncio.run(LLMReaders(s.model).read_facts(toy, MSG))
    assert got == Success((RawFact("carrier", "COURIER", Quoted("by courier")),))
    assert "refund is derived" in s.retry_prompts()[0]


def test_facts_rejected_twice_are_malformed(toy):
    s = Script({"facts": [{"var": "carrier", "value": "POST", "quote": "by post"}]})
    assert isinstance(asyncio.run(LLMReaders(s.model).read_facts(toy, MSG)), Failure)
    assert asyncio.run(LLMReaders(s.model).read_facts(toy, MSG)).failure().__class__ is Malformed


def test_claims_are_read_as_expression_trees(toy):
    reply = "It was 3 days late, so you get a refund, not a voucher."
    s = Script({"claims": [{"expr": {"ge": ["daysLate", 3]}, "quote": "3 days late"},
                           {"expr": {"and": ["refund", {"not": "voucher"}]}, "quote": "a refund, not a voucher"}]})
    got = asyncio.run(LLMReaders(s.model).read_claims(toy, reply))
    assert got == Success((RawClaim({"ge": ["daysLate", 3]}, "3 days late"),
                           RawClaim({"and": ["refund", {"not": "voucher"}]}, "a refund, not a voucher")))


def test_a_claim_with_no_variable_is_retried(toy):
    reply = "So it counts as late."
    s = Script({"claims": [{"expr": True, "quote": "counts as late"}]},
               {"claims": [{"expr": "isLate", "quote": "counts as late"}]})
    assert asyncio.run(LLMReaders(s.model).read_claims(toy, reply)) == Success((RawClaim("isLate", "counts as late"),))
    assert "mentions no policy variable" in s.retry_prompts()[0]


def test_a_rewrite_runs_warmer_and_lists_the_problems(toy):
    s = Script("You'll get a refund.")
    got = asyncio.run(LLMReaders(s.model).rewrite("You'll get a voucher.", (Problem("x", "it contradicts"),), ""))
    assert got == Success("You'll get a refund.")
    assert s.infos[0].model_settings == {"temperature": 0.3} and "- it contradicts" in s.infos[0].instructions


def test_provider_errors_are_mapped(toy):
    down = Script(ModelHTTPError(503, "m", body="busy"))
    assert isinstance(answer(down, toy).failure(), Unavailable)
    blocked = Script(ContentFilterError("filtered"))
    assert isinstance(answer(blocked, toy).failure(), Refused)


def test_llm_readers_implement_every_port():
    r = LLMReaders(Script("x").model)
    ports: tuple[AnswerReader, FactReader, ClaimReader, Rewriter] = (r, r, r, r)  # checked by ty
    assert all(ports)
