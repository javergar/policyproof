"""Effects: reading facts, answers and claims out of text with LLMs or Jev, and the two pipelines built on them.

`ports` defines what a reader is; `consensus` combines two readers; `pipeline` runs a turn. None of these import a
provider SDK: the pydantic-ai readers live in `effects.llm` (extra `[llm]`) and `effects.jev` (extra `[jev]`).
"""
