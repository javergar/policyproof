"""Running an agent with no exception crossing the port: provider and output failures become `LLMError`s."""
from pydantic_ai import Agent
from pydantic_ai.exceptions import ContentFilterError, ModelAPIError, UnexpectedModelBehavior
from returns.result import Failure, Result, Success

from policyproof.effects.errors import LLMError, Malformed, Refused, Unavailable


async def run[T](agent: Agent[None, T], prompt: str) -> Result[T, LLMError]:
    try:
        return Success((await agent.run(prompt)).output)
    except ContentFilterError as e:
        return Failure(Refused(str(e)))
    except UnexpectedModelBehavior as e:
        return Failure(Malformed(str(e)))
    except ModelAPIError as e:
        return Failure(Unavailable(str(e)))
