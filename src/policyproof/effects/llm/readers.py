"""All four ports on any chat model pydantic-ai supports.

Each call runs one pydantic-ai `Agent` with a structured output type. The matching guard runs in the agent's output
validator, so an output the guard rejects is sent back once with the guard's reasons (`retries`). When the retries run
out, facts and claims are `Malformed` (the pipelines then go on without facts or fall back), while an answer is
`Unclear`, so the question is asked again rather than the turn failing.
"""
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic_ai import Agent, ModelRetry
from pydantic_ai.exceptions import ContentFilterError, ModelAPIError, UnexpectedModelBehavior
from pydantic_ai.models import Model
from pydantic_ai.settings import ModelSettings
from returns.result import Failure, Result, Success

from policyproof.core._result import unreachable
from policyproof.core.check import Problem
from policyproof.core.facts import Quoted
from policyproof.core.syntax import CheckedPolicy
from policyproof.effects.errors import LLMError, Malformed, Refused, Unavailable
from policyproof.effects.llm.exprmodel import Claims, Real
from policyproof.effects.llm.prompts import answer_prompt, claims_prompt, facts_prompt, rewrite_prompt
from policyproof.effects.ports import NotAnswered, RawAnswer, RawClaim, RawFact, Rejected, Said, Unclear
from policyproof.guards import answer, claims, facts

type Value = bool | int | str | Real


class _Out(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class AnswerOut(_Out):
    """How the customer's reply answers the question."""
    status: Literal["answered", "unclear", "not_answered"]
    value: Value | None = Field(None, description="The answer, when status is answered.")
    quote: str | None = Field(None, description="The reply's exact words that give the answer.")
    reason: str | None = Field(None, description="Why the reply can't be read, when status is unclear.")


class FactOut(_Out):
    var: str = Field(description="The variable's name, exactly as listed.")
    value: Value
    quote: str = Field(description="The message's exact words that state the fact.")


class FactsOut(_Out):
    """Every fact the message states about the listed variables."""
    facts: list[FactOut]


def _plain(v: Value | None) -> object:
    return v.model_dump() if isinstance(v, Real) else v


def _raw_answer(out: AnswerOut) -> RawAnswer:
    match out.status:
        case "answered" if out.quote is not None and out.value is not None:
            return Said(_plain(out.value), out.quote)
        case "answered":
            return Unclear("answered without a value and a quote")
        case "unclear":
            return Unclear(out.reason or "unclear")
        case "not_answered":
            return NotAnswered()


def _raw_facts(out: FactsOut) -> tuple[RawFact, ...]:
    return tuple(RawFact(f.var, _plain(f.value), Quoted(f.quote)) for f in out.facts)


def _raw_claims(out: Claims) -> tuple[RawClaim, ...]:
    return tuple(RawClaim(c.model_dump()["expr"], c.quote) for c in out.claims)


def _reasons(rejected: tuple[Rejected, ...]) -> str:
    return "; ".join(f"{r.item}: {r.reason}" for r in rejected)


async def _run[T](agent: Agent[None, T], prompt: str) -> Result[T, LLMError]:
    try:
        return Success((await agent.run(prompt)).output)
    except ContentFilterError as e:
        return Failure(Refused(str(e)))
    except UnexpectedModelBehavior as e:
        return Failure(Malformed(str(e)))
    except ModelAPIError as e:
        return Failure(Unavailable(str(e)))


@dataclass(frozen=True, slots=True)
class LLMReaders:
    """An `AnswerReader`, `FactReader`, `ClaimReader` and `Rewriter` on one pydantic-ai model."""
    model: Model
    retries: int = 1
    rewrite_settings: ModelSettings = field(default_factory=lambda: ModelSettings(temperature=0.3))

    def _agent[T](self, output: type[T], instructions: str) -> Agent[None, T]:
        return Agent(self.model, output_type=output, instructions=instructions, retries={"output": self.retries})

    async def read_answer(self, p: CheckedPolicy, var: str, message: str) -> Result[RawAnswer, LLMError]:
        agent = self._agent(AnswerOut, answer_prompt(p, var))

        @agent.output_validator
        def _guard(out: AnswerOut) -> AnswerOut:
            raw = _raw_answer(out)
            if isinstance(raw, Said) and isinstance(reading := answer.check(p, var, message, raw), Unclear):
                raise ModelRetry(f"answer rejected: {reading.reason}")
            return out

        match await _run(agent, message):
            case Success(out):
                return Success(_raw_answer(out))
            case Failure(Malformed(reason)):
                return Success(Unclear(f"the answer couldn't be read: {reason}"))
            case Failure(e):
                return Failure(e)
            case _:
                unreachable()

    async def read_facts(self, p: CheckedPolicy, message: str) -> Result[tuple[RawFact, ...], LLMError]:
        agent = self._agent(FactsOut, facts_prompt(p))

        @agent.output_validator
        def _guard(out: FactsOut) -> FactsOut:
            _, rejected = facts.check(p, message, _raw_facts(out))
            if rejected:
                raise ModelRetry(f"facts rejected: {_reasons(rejected)}")
            return out

        return (await _run(agent, message)).map(_raw_facts)

    async def read_claims(self, p: CheckedPolicy, reply: str) -> Result[tuple[RawClaim, ...], LLMError]:
        agent = self._agent(Claims, claims_prompt(p))

        @agent.output_validator
        def _guard(out: Claims) -> Claims:
            _, rejected = claims.check(p, reply, _raw_claims(out))
            if rejected:
                raise ModelRetry(f"claims rejected: {_reasons(rejected)}")
            return out

        return (await _run(agent, reply)).map(_raw_claims)

    async def rewrite(self, draft: str, problems: tuple[Problem, ...], instructions: str) -> Result[str, LLMError]:
        agent = Agent(self.model, output_type=str, instructions=rewrite_prompt(problems, instructions),
                      model_settings=self.rewrite_settings)
        return await _run(agent, draft)
