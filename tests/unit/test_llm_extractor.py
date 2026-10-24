"""LLMExtractor against pydantic-ai's FunctionModel: scripted outputs, no network."""
import asyncio
import json

from pydantic_ai.messages import ModelMessage, ModelRequest, ModelResponse, RetryPromptPart, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from returns.result import Failure

from policyproof.authoring.document import Anchor, parse
from policyproof.authoring.extraction import Link
from policyproof.authoring.llm.extractor import LLMExtractor
from policyproof.core.syntax import When
from policyproof.effects.errors import Malformed

DOC = parse("## Couriers\n\n- Courier parcels are never refunded.\n- Lost parcels are always refunded.\n\n"
            "We aim to reply within two days.\n")
COURIERS, LOST, REPLY = (s.anchor for s in DOC.sentences)


class Script:
    def __init__(self, *outputs: object):
        self.outputs, self.requests = outputs, []
        self.model = FunctionModel(self.respond)

    def respond(self, messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        self.requests.append(messages)
        out = self.outputs[min(len(self.requests), len(self.outputs)) - 1]
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, json.dumps(out))])

    def retry_prompts(self) -> list[str]:
        return [str(p.content) for m in self.requests[-1] if isinstance(m, ModelRequest) for p in m.parts
                if isinstance(p, RetryPromptPart)]


def output(then_lost: object = "refund", variables: list | None = None) -> dict:
    return {
        "sorts": [{"name": "Carrier", "values": ["POST", "COURIER"]}],
        "variables": variables if variables is not None else [
            {"name": "carrier", "sort": "Carrier", "role": "system", "description": "Who delivered the parcel.",
             "display": {"COURIER": "Came by courier", "POST": "Came by post"}},
            {"name": "lost", "sort": "Bool", "role": "system", "description": "The parcel was lost."},
            {"name": "refund", "sort": "Bool", "role": "derived", "description": "The customer gets a refund."}],
        "rules": [
            {"sentence": 1, "kind": "when", "when": {"eq": ["carrier", "COURIER"]}, "then": {"not": "refund"}},
            {"sentence": 2, "kind": "when", "when": "lost", "then": then_lost}],
        "outcomes": [{"name": "refund", "assignment": {"refund": True}, "display": "A refund"},
                     {"name": "nothing", "assignment": {"refund": False}}],
    }


def extract(script, **kw):
    return asyncio.run(LLMExtractor(script.model).extract(DOC, **kw))


def test_extracts_and_links():
    ex = extract(Script(output())).unwrap()
    assert [r.id for r in ex.policy.rules] == ["R1", "R2"]
    assert isinstance(ex.policy.rules[1], When)
    assert ex.links == (Link("R1", COURIERS), Link("R2", LOST))
    assert ex.uncovered == (REPLY,)


def test_ill_typed_output_is_sent_back():
    s = Script(output(then_lost="refnd"), output())
    assert extract(s).unwrap().links == (Link("R1", COURIERS), Link("R2", LOST))
    assert any("refnd" in p for p in s.retry_prompts())


def test_a_sentence_number_must_be_listed():
    bad = output()
    bad["rules"][0]["sentence"] = 9
    s = Script(bad, output())
    extract(s).unwrap()
    assert any("9" in p for p in s.retry_prompts())


def test_vocabulary_names_must_survive():
    vocabulary = extract(Script(output())).unwrap().policy
    no_lost = output(then_lost={"not": "refund"})
    no_lost["variables"] = [v for v in no_lost["variables"] if v["name"] != "lost"]
    no_lost["rules"][1]["when"] = True
    no_lost["rules"] = [no_lost["rules"][1]]
    s = Script(no_lost, {**output(), "rules": [output()["rules"][1]]})
    extract(s, vocabulary=vocabulary, only=(LOST,)).unwrap()
    assert any("lost" in p for p in s.retry_prompts())


def test_only_limits_the_sentences_and_the_uncovered():
    s = Script({**output(), "rules": [output()["rules"][1]]})
    ex = extract(s, only=(LOST,)).unwrap()
    assert ex.links == (Link("R1", LOST),) and ex.uncovered == ()


def test_retries_run_out_as_malformed():
    result = extract(Script(output(then_lost="refnd")))
    assert isinstance(result, Failure) and isinstance(result.failure(), Malformed)


def test_an_unlisted_anchor_in_only_is_ignored():
    ex = extract(Script(output()), only=(Anchor("Nowhere", "Not here."), COURIERS, LOST)).unwrap()
    assert ex.links == (Link("R1", COURIERS), Link("R2", LOST))
