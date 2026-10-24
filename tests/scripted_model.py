"""A pydantic-ai FunctionModel that returns scripted outputs in order (the last repeats) and records each request.
A dict is sent as the structured output; a string as plain text."""
import json

from pydantic_ai.messages import ModelMessage, ModelRequest, ModelResponse, RetryPromptPart, TextPart, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel


class Script:
    def __init__(self, *outputs: object):
        self.outputs, self.requests, self.infos = outputs, [], []
        self.model = FunctionModel(self.respond)

    def respond(self, messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        self.requests.append(messages)
        self.infos.append(info)
        out = self.outputs[min(len(self.requests), len(self.outputs)) - 1]
        if isinstance(out, str):
            return ModelResponse(parts=[TextPart(out)])
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, json.dumps(out))])

    def retry_prompts(self) -> list[str]:
        return [str(p.content) for m in self.requests[-1] if isinstance(m, ModelRequest) for p in m.parts
                if isinstance(p, RetryPromptPart)]

    def instructions(self) -> str:
        return self.infos[-1].instructions or ""
