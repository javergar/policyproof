"""JevReaders against an offline TypeSafeModel: `decide` is overridden to record the questions and return scripted
answers, so these tests pin exactly what Jev is asked without network access or a key."""
import asyncio

from conftest import POLICIES, load
from pydantic_ai.exceptions import ModelAPIError
from pydantic_ai.models.decision import (
    ChoiceAnswer,
    ChoiceQuestion,
    DecisionModelSettings,
    DecisionRequest,
    DecisionResponse,
    UnsureRoute,
)
from pydantic_ai.models.typesafe import TypeSafeModel
from pydantic_ai.providers.typesafe import TypeSafeProvider
from pydantic_ai.usage import RequestUsage
from returns.result import Success
from typesafe_sdk import AsyncTypeSafeClient

from policyproof.core.codec import from_yaml
from policyproof.core.facts import Scored
from policyproof.effects.errors import Refused, Unavailable
from policyproof.effects.jev.readers import JevReaders
from policyproof.effects.ports import AnswerReader, FactReader, NotAnswered, RawFact, Said, Unclear


class Offline(TypeSafeModel):
    def __init__(self, picks: dict[str, tuple[str, float]] | Exception):
        super().__init__("jev-1.13.0", provider=TypeSafeProvider(typesafe_client=AsyncTypeSafeClient(api_key="x")))
        self.picks, self.questions = picks, {}

    async def decide(self, request: DecisionRequest, model_settings: DecisionModelSettings) -> DecisionResponse:
        if isinstance(self.picks, Exception):
            raise self.picks
        self.questions = dict(request.questions)
        answers = {}
        for name, q in request.questions.items():
            assert isinstance(q, ChoiceQuestion)
            pick, p = self.picks[name]
            others = [o for o in q.criteria if o != pick]
            probs = {pick: p, **{o: (1 - p) / len(others) for o in others}}
            answers[name] = ChoiceAnswer(choice=pick, confidence=p, probabilities=probs)
        return DecisionResponse(answers=answers, model_name="jev-1.13.0", usage=RequestUsage())


MSG = "It came by courier, and I'd like my money back."


def test_facts_ask_one_choice_per_boolean_or_enum_variable(toy):
    jev = Offline({"carrier": ("COURIER", 0.9), "wantsRefund": ("true", 0.8)})
    got = asyncio.run(JevReaders(jev).read_facts(toy, MSG))
    assert got == Success((RawFact("carrier", "COURIER", Scored(0.9)), RawFact("wantsRefund", "true", Scored(0.8))))
    assert set(jev.questions) == {"carrier", "wantsRefund"}  # daysLate is an Int: Jev can't be asked it
    q = jev.questions["wantsRefund"]
    assert isinstance(q, ChoiceQuestion) and set(q.criteria) == {"true", "false", "not_stated"}
    assert isinstance(q.instructions, dict) and q.instructions["question"] == "Would you like your money back?"


def test_variables_the_message_does_not_mention_are_left_out(toy):
    jev = Offline({"carrier": ("not_stated", 0.95), "wantsRefund": ("true", 0.8)})
    got = asyncio.run(JevReaders(jev).read_facts(toy, MSG))
    assert got == Success((RawFact("wantsRefund", "true", Scored(0.8)),))


def test_an_answer_is_read_with_the_whole_message_as_its_quote(toy):
    jev = Offline({"response": ("true", 0.9)})
    assert asyncio.run(JevReaders(jev).read_answer(toy, "wantsRefund", "Yes please")) == Success(Said("true",
                                                                                                    "Yes please"))
    q = jev.questions["response"]
    assert isinstance(q, ChoiceQuestion) and set(q.criteria) == {"true", "false", "unclear", "not_answered"}


def test_a_low_confidence_answer_is_unclear(toy):
    jev = Offline({"response": ("true", 0.4)})
    assert asyncio.run(JevReaders(jev).read_answer(toy, "wantsRefund", "maybe")) == Success(Unclear("low confidence"))


def test_unclear_and_unanswered_are_reported(toy):
    for pick, want in [("unclear", Unclear("unclear")), ("not_answered", NotAnswered())]:
        jev = Offline({"response": (pick, 0.9)})
        assert asyncio.run(JevReaders(jev).read_answer(toy, "wantsRefund", "hm")) == Success(want)


def test_hand_offs_are_refused_and_api_errors_unavailable(toy):
    hand_off = UnsureRoute("jev-1.13.0", "Facts", {"Facts": 0.3}, 0.5)
    unsure = asyncio.run(JevReaders(Offline(hand_off)).read_facts(toy, MSG))
    assert isinstance(unsure.failure(), Refused)
    down = asyncio.run(JevReaders(Offline(ModelAPIError("jev", "down"))).read_facts(toy, MSG))
    assert isinstance(down.failure(), Unavailable)


def test_jev_readers_implement_the_ports():
    r = JevReaders(Offline({}))
    ports: tuple[AnswerReader, FactReader] = (r, r)  # checked by ty
    assert all(ports)


def test_variable_names_pydantic_reserves_still_work():
    text = (POLICIES / "toy.yaml").read_text().replace("wantsRefund", "model_config").replace("carrier", "schema")
    p = from_yaml(text).unwrap()
    jev = Offline({"schema": ("COURIER", 0.9), "model_config": ("true", 0.8)})
    got = asyncio.run(JevReaders(jev).read_facts(p, MSG))
    assert got == Success((RawFact("schema", "COURIER", Scored(0.9)), RawFact("model_config", "true", Scored(0.8))))
    assert set(jev.questions) == {"schema", "model_config"}


def test_a_policy_with_nothing_jev_can_ask_makes_no_call():
    jev = Offline(ModelAPIError("jev", "must not be called"))
    assert asyncio.run(JevReaders(jev).read_facts(load("weights.yaml"), "It weighs 30 kg")) == Success(())


def test_jev_refuses_number_answers_so_consensus_uses_the_other_reader():
    jev = Offline(ModelAPIError("jev", "must not be called"))
    got = asyncio.run(JevReaders(jev).read_answer(load("weights.yaml"), "kg", "About 30 kg"))
    assert isinstance(got.failure(), Refused)
