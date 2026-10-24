"""The `Drafter` port on any pydantic-ai model: edits to the document that make it say what the author decided."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, assert_never

from pydantic import BaseModel, ConfigDict, Field
from pydantic_ai import Agent, ModelRetry
from pydantic_ai.models import Model
from pydantic_ai.settings import ModelSettings
from returns.result import Result

from policyproof.authoring.document import Anchor, Document, Edit, Insert, Remove, Replace
from policyproof.authoring.llm._call import run
from policyproof.authoring.llm.prompts import draft_prompt
from policyproof.authoring.ports import Answer, Situation
from policyproof.effects.errors import LLMError


class EditOut(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: Literal["replace", "insert", "remove"]
    section: str = Field(description="The section's heading, exactly.")
    sentence: str | None = Field(description="The current sentence, quoted exactly (for insert: the one to put the "
                                             "new text after, or null for the end of the section).")
    text: str | None = Field(description="The new text (null for remove).")


class EditsOut(BaseModel):
    """The edits, in the order to apply them."""
    model_config = ConfigDict(extra="forbid", frozen=True)
    edits: list[EditOut]


def _problems(out: EditsOut) -> list[str]:
    found = []
    for i, e in enumerate(out.edits):
        if e.kind != "remove" and not (e.text or "").strip():
            found.append(f"edits[{i}]: a {e.kind} needs the new text")
        if e.kind in ("replace", "remove") and not (e.sentence or "").strip():
            found.append(f"edits[{i}]: a {e.kind} needs the current sentence, quoted")
    return found


def _edits(out: EditsOut) -> tuple[Edit, ...]:
    """Quoted sentences become anchors. Edits apply one after another, so a quote always means the first copy of that
    sentence still in the document: a replaced or removed copy is gone by the time the next edit looks."""
    def anchor(section: str, sentence: str) -> Anchor:
        return Anchor(section, " ".join(sentence.split()))

    result: list[Edit] = []
    for e in out.edits:
        match e.kind:
            case "replace":
                result.append(Replace(anchor(e.section, e.sentence or ""), e.text or ""))
            case "insert":
                result.append(Insert(e.section, anchor(e.section, e.sentence) if e.sentence else None, e.text or ""))
            case "remove":
                result.append(Remove(anchor(e.section, e.sentence or "")))
            case _:
                assert_never(e.kind)
    return tuple(result)


@dataclass(frozen=True, slots=True)
class LLMDrafter:
    """A `Drafter` on one pydantic-ai model."""
    model: Model
    retries: int = 1
    settings: ModelSettings | None = None

    async def draft(self, doc: Document, situation: Situation, answer: Answer,
                    failure: str | None) -> Result[tuple[Edit, ...], LLMError]:
        agent = Agent(self.model, output_type=EditsOut, retries={"output": self.retries},
                      instructions=draft_prompt(doc, situation, answer, failure), model_settings=self.settings)

        @agent.output_validator
        def _guard(out: EditsOut) -> EditsOut:
            if problems := _problems(out):
                raise ModelRetry("; ".join(problems))
            return out

        return (await run(agent, "Write the edits.")).map(_edits)
