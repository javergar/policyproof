"""Guards: pure checks on what a reader (an LLM or Jev) returned, before any of it reaches the core.

A reader returns raw data (`guards.raw`). A guard keeps only what it can verify against the policy and the text the
reader read, and says why it dropped the rest. Guards import only `policyproof.core`, so the same functions run inside
a reader (to ask the model to retry) and after it (so nothing unchecked gets through).
"""
