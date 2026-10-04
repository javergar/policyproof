"""One customer turn on the toy policy, end to end, with a Bedrock model.

    uv sync && PP_BEDROCK_MODEL=au.anthropic.claude-haiku-4-5-20251001-v1:0 AWS_PROFILE=... \\
        uv run python examples/turn.py

The parcel is 3 days late (a fact from the tracking system); the policy asks whether the customer wants their money
back. The customer's reply is read into a fact, the policy decides, and a drafted reply is checked before sending.
"""
import asyncio
import os
from pathlib import Path

from pydantic_ai.models.bedrock import BedrockConverseModel

from policyproof.core.codec import from_yaml
from policyproof.core.decide import Decided, NeedInfo, decide
from policyproof.core.facts import Fact, FromSystem, facts
from policyproof.core.solver import compile
from policyproof.core.syntax import IntLit
from policyproof.effects.llm.readers import LLMReaders
from policyproof.effects.pipeline import Conversation, Readers, guard_reply, read_turn

POLICY = Path(__file__).parent.parent / "tests" / "policies" / "toy.yaml"


async def main() -> None:
    c = compile(from_yaml(POLICY.read_text()).unwrap())
    llm = LLMReaders(BedrockConverseModel(os.environ["PP_BEDROCK_MODEL"]))
    known = facts(Fact("daysLate", IntLit(3), FromSystem("tracking")))
    question = decide(c, known)
    assert isinstance(question, NeedInfo)
    print(f"Agent: {question.question}")

    message = "Yes please, I'd like my money back."
    print(f"Customer: {message}")
    turn = (await read_turn(c, Conversation(known, question, frozenset()), message, Readers(llm, llm))).unwrap()
    d = turn.decision
    print(f"Decision: {d.outcome} (rules {', '.join(d.rules)})" if isinstance(d, Decided) else f"Decision: {d}")

    draft = "Sorry about the delay! Since it was 3 days late, you'll get a voucher."
    guarded = await guard_reply(c, turn.state.facts, turn.decision, draft, llm, llm)
    print(f"Draft: {draft}")
    print(f"Sent ({'fallback' if guarded.fell_back else f'attempt {guarded.attempts}'}): {guarded.text}")


if __name__ == "__main__":
    asyncio.run(main())
