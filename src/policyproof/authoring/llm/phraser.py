"""The `Phraser` port on any pydantic-ai model: a situation's title, and a rule as a plain sentence."""
from __future__ import annotations

from dataclasses import dataclass

from pydantic_ai import Agent, ModelRetry
from pydantic_ai.models import Model
from returns.result import Result

from policyproof.authoring.llm._call import run
from policyproof.authoring.llm.prompts import sentence_prompt, title_prompt
from policyproof.core.syntax import CheckedPolicy, Rule
from policyproof.effects.errors import LLMError

MAX_TITLE_WORDS = 20


@dataclass(frozen=True, slots=True)
class LLMPhraser:
    """A `Phraser` on one pydantic-ai model."""
    model: Model
    retries: int = 1

    def _agent(self, instructions: str, max_words: int | None) -> Agent[None, str]:
        agent = Agent(self.model, output_type=str, retries={"output": self.retries}, instructions=instructions)

        @agent.output_validator
        def _guard(text: str) -> str:
            if not text.strip():
                raise ModelRetry("answer with the sentence")
            if max_words is not None and len(text.split()) > max_words:
                raise ModelRetry(f"use at most {max_words} words")
            return text.strip()

        return agent

    async def title(self, p: CheckedPolicy, customer: tuple[str, ...]) -> Result[str, LLMError]:
        return await run(self._agent(title_prompt(p, customer), MAX_TITLE_WORDS), "Write the sentence.")

    async def sentence(self, p: CheckedPolicy, rule: Rule) -> Result[str, LLMError]:
        return await run(self._agent(sentence_prompt(p, rule), None), "Write the sentence.")
