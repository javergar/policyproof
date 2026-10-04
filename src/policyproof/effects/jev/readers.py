"""Facts and answers from Jev.

Jev answers typed questions with probabilities instead of writing text. pydantic-ai's `TypeSafeModel` turns an
output type into Jev questions, so each reader builds one from the policy: a pick-one per variable, over the
variable's values plus "not stated" (facts) or "unclear" and "not answered" (answers). Jev can't point to the words it
read, so facts carry `Scored` evidence (its confidence) and an answer quotes the whole message. Int and Real
variables can't be asked as a pick-one: facts skip them and an answer to one is `Refused`, so pair Jev with an LLM
(`consensus.AgreeingFacts`, `AgreeingAnswers`) for those.
"""
from dataclasses import dataclass
from typing import Annotated, Any, assert_never

from pydantic import BaseModel, Field, create_model
from pydantic_ai import Agent, Choices
from pydantic_ai.exceptions import ModelAPIError, UnexpectedModelBehavior
from pydantic_ai.messages import ModelResponse
from pydantic_ai.models import Model
from pydantic_ai.models.decision import DecisionHandOff
from pydantic_ai.run import AgentRunResult
from returns.result import Failure, Result, Success

from policyproof.core._result import unreachable
from policyproof.core.facts import Scored
from policyproof.core.syntax import Ask, BoolSort, CheckedPolicy, Derived, EnumSort, IntSort, RealSort, Sort, Variable
from policyproof.effects.errors import LLMError, Malformed, Refused, Unavailable
from policyproof.effects.ports import NotAnswered, RawAnswer, RawFact, Said, Unclear

NOT_STATED, UNCLEAR, NOT_ANSWERED = "not_stated", "unclear", "not_answered"


def options(v: Variable) -> dict[str, str] | None:
    """The variable's values as described pick-one options, or None if it can't be asked as one."""
    s: Sort = v.sort
    match s:
        case BoolSort():
            return {"true": f"Yes: {v.description}", "false": f"No, the opposite: {v.description}"}
        case EnumSort(_, values):
            return {x: f"{v.description}: {x}" for x in values}
        case IntSort() | RealSort():
            return None
        case _:
            assert_never(s)


def question(v: Variable) -> str:
    return v.role.question if isinstance(v.role, Ask) else v.description


def facts_type(p: CheckedPolicy) -> type[BaseModel] | None:
    """One pick-one field per variable Jev can be asked about, or None if there is none. Fields are named `f0`, `f1`,
    ... and carry the variable's name as their alias, so a variable named like a pydantic attribute still works."""
    fields: dict[str, Any] = {}
    for v in p.variables:
        found = options(v)
        if found is not None and not isinstance(v.role, Derived):
            choices = Choices({**found, NOT_STATED: "The message doesn't say."})
            fields[f"f{len(fields)}"] = (Annotated[str, choices, Field(alias=v.name, description=question(v))], ...)
    if not fields:
        return None
    return create_model("Facts", __doc__="What the customer's message states about each variable.", **fields)


def answer_type(v: Variable) -> type[str]:
    found = options(v) or {}
    return Choices({**found, UNCLEAR: "The reply tries to answer but can't be read as one of these.",
                    NOT_ANSWERED: "The reply doesn't answer the question."}, name=v.name, description=question(v))


def confidences(run: AgentRunResult[Any]) -> dict[str, float]:
    found: dict[str, float] = {}
    for m in run.all_messages():
        if isinstance(m, ModelResponse) and m.provider_details:
            found.update(m.provider_details.get("confidence", {}))
    return found


async def _run[T](agent: Agent[None, T], prompt: str) -> Result[AgentRunResult[T], LLMError]:
    try:
        return Success(await agent.run(prompt))
    except DecisionHandOff as e:
        return Failure(Refused(str(e)))
    except UnexpectedModelBehavior as e:
        return Failure(Malformed(str(e)))
    except ModelAPIError as e:
        return Failure(Unavailable(str(e)))


@dataclass(frozen=True, slots=True)
class JevReaders:
    """A `FactReader` and an `AnswerReader` on Jev. Pass a `TypeSafeModel` (pin a version, e.g. `jev-1.13.0`)."""
    model: Model
    min_confidence: float = 0.5

    async def read_facts(self, p: CheckedPolicy, message: str) -> Result[tuple[RawFact, ...], LLMError]:
        output = facts_type(p)
        if output is None:
            return Success(())
        match await _run(Agent(self.model, output_type=output), message):
            case Success(run):
                conf = confidences(run)
                picked = run.output.model_dump(by_alias=True)
                return Success(tuple(RawFact(var, value, Scored(conf.get(var, 0.0)))
                                     for var, value in picked.items() if value != NOT_STATED))
            case Failure(e):
                return Failure(e)
            case _:
                unreachable()

    async def read_answer(self, p: CheckedPolicy, var: str, message: str) -> Result[RawAnswer, LLMError]:
        v = next(x for x in p.variables if x.name == var)
        if options(v) is None:
            return Failure(Refused(f"Jev can't read a number for {var}; use an LLM reader for it"))
        agent = Agent(self.model, output_type=answer_type(v))
        match await _run(agent, message):
            case Success(run):
                confidence = next(iter(confidences(run).values()), 0.0)
                if run.output == NOT_ANSWERED:
                    return Success(NotAnswered())
                if run.output == UNCLEAR:
                    return Success(Unclear(UNCLEAR))
                if confidence < self.min_confidence:
                    return Success(Unclear("low confidence"))
                return Success(Said(run.output, message))
            case Failure(e):
                return Failure(e)
            case _:
                unreachable()
