"""The `Extractor` port on any chat model pydantic-ai supports: the whole document in one request, every rule citing the
sentence it came from. The output is decoded by the policy codec inside the agent's output validator, so an ill-typed
policy, an unknown sentence number or a dropped vocabulary name is sent back to the model with the reasons."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic_ai import Agent, ModelRetry
from pydantic_ai.exceptions import ContentFilterError, ModelAPIError, UnexpectedModelBehavior
from pydantic_ai.models import Model
from returns.result import Failure, Result, Success

from policyproof.authoring.document import Anchor, Document
from policyproof.authoring.extraction import Extraction, Link
from policyproof.authoring.llm.prompts import extraction_prompt
from policyproof.core._result import unreachable
from policyproof.core.codec import Data, DecodeError, IllTyped, decode
from policyproof.core.syntax import CheckedPolicy
from policyproof.effects.errors import LLMError, Malformed, Refused, Unavailable
from policyproof.effects.llm.exprmodel import Expr


class _Out(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, validate_by_name=True, serialize_by_alias=True)


class SortOut(_Out):
    name: str
    values: list[str]


class VariableOut(_Out):
    name: str
    sort: str = Field(description="Bool, Int, Real, or the name of one of the sorts.")
    role: Literal["system", "ask", "derived"]
    question: str | None = Field(None, description="For role ask: the question the agent asks.")
    description: str = Field(description="What the variable means, literally.")
    display: dict[str, str] | str | None = Field(None, description="How an author reads each value.")


class RuleOut(_Out):
    sentence: int = Field(description="The number of the sentence this rule comes from.")
    kind: Literal["when", "define", "constraint"]
    when: Expr | None = None
    then: Expr | None = None
    var: str | None = Field(None, description="For define: the variable defined.")
    as_: Expr | None = Field(None, alias="as", description="For define: when the variable holds.")
    expr: Expr | None = Field(None, description="For constraint: what always holds.")


class OutcomeOut(_Out):
    name: str
    assignment: dict[str, bool | int | str]
    display: str | None = None


class ExtractionOut(_Out):
    """The policy the document states."""
    sorts: list[SortOut]
    variables: list[VariableOut]
    rules: list[RuleOut]
    outcomes: list[OutcomeOut]


def _rule(i: int, r: dict[str, Data]) -> Result[dict[str, Data], str]:
    out: dict[str, Data] = {"id": f"R{i}", "source": f"sentence {r['sentence']}"}
    match r["kind"]:
        case "when" if r.get("when") is not None and r.get("then") is not None:
            return Success(out | {"when": r["when"], "then": r["then"]})
        case "define" if r.get("var") is not None and r.get("as") is not None:
            return Success(out | {"define": {"var": r["var"], "as": r["as"]}})
        case "constraint" if r.get("expr") is not None:
            return Success(out | {"constraint": r["expr"]})
        case kind:
            need = {"when": "when and then", "define": "var and as", "constraint": "expr"}.get(str(kind), "a kind")
            return Failure(f"rules[{i - 1}]: a {kind} rule needs {need}")


def _data(out: ExtractionOut, vocabulary: CheckedPolicy | None) -> Result[dict[str, Data], str]:
    dumped = out.model_dump(exclude_none=True)
    rules: list[Data] = []
    for i, r in enumerate(dumped["rules"], start=1):
        match _rule(i, r):
            case Success(rule):
                rules.append(rule)
            case Failure(message):
                return Failure(message)
            case _:
                unreachable()
    variables: dict[str, Data] = {}
    for v in dumped["variables"]:
        variables[v["name"]] = {k: v[k] for k in ("sort", "role", "question", "description", "display") if k in v}
    return Success({
        "policy": vocabulary.name if vocabulary is not None else "policy",
        "version": vocabulary.version if vocabulary is not None else "1",
        "sorts": {s["name"]: s["values"] for s in dumped["sorts"]},
        "variables": variables,
        "rules": rules,
        "outcomes": {o["name"]: {**o["assignment"], **({"display": o["display"]} if "display" in o else {})}
                     for o in dumped["outcomes"]},
    })


def _missing_names(p: CheckedPolicy, vocabulary: CheckedPolicy) -> list[str]:
    have = {s.name for s in p.sorts} | {v.name for v in p.variables} | {o.name for o in p.outcomes}
    want = [s.name for s in vocabulary.sorts] + [v.name for v in vocabulary.variables] + \
        [o.name for o in vocabulary.outcomes]
    return [n for n in want if n not in have]


def _convert(out: ExtractionOut, doc: Document, vocabulary: CheckedPolicy | None,
             only: tuple[Anchor, ...] | None) -> Result[Extraction, str]:
    numbered = {i: s.anchor for i, s in enumerate(doc.sentences, start=1)}
    listed = [i for i, a in numbered.items() if only is None or a in only]
    wrong = [r.sentence for r in out.rules if r.sentence not in listed]
    if wrong:
        return Failure(f"rules cite sentences {wrong}, but only sentences {listed} may be cited")
    match _data(out, vocabulary):
        case Success(data):
            pass
        case Failure(message):
            return Failure(message)
        case _:
            unreachable()
    match decode(data):
        case Success(policy):
            pass
        case Failure(DecodeError() as e):
            return Failure(f"{e.path}: {e.message}")
        case Failure(IllTyped(errors)):
            return Failure("; ".join(str(e) for e in errors))
        case _:
            unreachable()
    if vocabulary is not None and (missing := _missing_names(policy, vocabulary)):
        return Failure(f"keep every name from the list; missing: {', '.join(missing)}")
    links = tuple(Link(f"R{i}", numbered[r.sentence]) for i, r in enumerate(out.rules, start=1))
    cited = {r.sentence for r in out.rules}
    return Success(Extraction(policy, links, tuple(numbered[i] for i in listed if i not in cited)))


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
class LLMExtractor:
    """An `Extractor` on one pydantic-ai model."""
    model: Model
    retries: int = 2

    async def extract(self, doc: Document, *, vocabulary: CheckedPolicy | None = None,
                      only: tuple[Anchor, ...] | None = None, guidance: str = "") -> Result[Extraction, LLMError]:
        agent = Agent(self.model, output_type=ExtractionOut, retries={"output": self.retries},
                      instructions=extraction_prompt(doc, vocabulary, only, guidance))

        @agent.output_validator
        def _guard(out: ExtractionOut) -> ExtractionOut:
            match _convert(out, doc, vocabulary, only):
                case Failure(message):
                    raise ModelRetry(f"the policy was rejected: {message}")
                case _:
                    return out

        match await _run(agent, "Extract the policy."):
            case Success(out):
                return _convert(out, doc, vocabulary, only).alt(Malformed)
            case Failure(e):
                return Failure(e)
            case _:
                unreachable()
