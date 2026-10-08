# policyproof

Prove what an agent may decide and say, from a written policy.

A policy is a YAML file: enum sorts, typed variables (from a system, asked of the customer, or derived), rules as
expression trees, and named outcomes. `policyproof` checks the policy is sound, decides cases with the Z3 solver
(or picks the one question that settles them), and checks every claim in an agent's reply against the proof.

```python
from policyproof.core.codec import from_yaml
from policyproof.core.decide import decide
from policyproof.core.facts import Fact, FromSystem, facts
from policyproof.core.solver import compile
from policyproof.core.syntax import IntLit
from policyproof.core.validate import gate

policy = from_yaml(open("policy.yaml").read()).unwrap()
compiled = gate(compile(policy)).unwrap()          # fails on any validation error
decision = decide(compiled, facts(Fact("daysLate", IntLit(3), FromSystem("tracking"))))
```

The core (`policyproof.core`) is pure and deterministic: no LLMs, no network, no I/O.

## Reading text: `policyproof.effects`

Models read the text; the policy decides. A turn runs through two pipelines:

- `read_turn` reads the customer's message: the answer to the question asked last turn, and any facts they state.
- `guard_reply` checks a drafted reply's claims against the proof, rewrites it once if it fails, and otherwise sends
  a plain fallback, so unchecked text never reaches the customer.

```python
from pydantic_ai.models.bedrock import BedrockConverseModel   # or any model pydantic-ai supports
from policyproof.effects.llm.readers import LLMReaders
from policyproof.effects.pipeline import Conversation, Readers, guard_reply, read_turn

llm = LLMReaders(BedrockConverseModel("au.anthropic.claude-haiku-4-5-20251001-v1:0"))
turn = (await read_turn(compiled, Conversation(known, pending_question, frozenset()), message,
                        Readers(llm, llm))).unwrap()
sent = await guard_reply(compiled, turn.state.facts, turn.decision, draft, llm, llm)
```

`examples/turn.py` runs a whole turn. Install the readers with an extra, plus your provider's pydantic-ai extra:

```bash
uv add "policyproof[llm]" "pydantic-ai-slim[bedrock]"   # any chat model pydantic-ai supports
uv add "policyproof[jev]"                               # Jev, TypeSafe's decision model (facts and answers)
```

What each part does when something goes wrong (it always errs toward asking again, never toward deciding):

| Situation | Result |
|---|---|
| An answer's quote isn't in the message, its value has the wrong type, or it contradicts an opening "yes"/"no" | `Unclear`: the question is asked again |
| A stated fact can't be quoted, or Jev's confidence is under `min_confidence` (0.5) | the fact is dropped (`Turn.rejected`) |
| A fact Jev scored under `firm_confidence` (0.8) would change the decision | the customer is asked to confirm it |
| The answer reader fails | `read_turn` returns the error |
| The fact reader fails | the turn goes on without volunteered facts (`Turn.degraded`) |
| A reply's claim can't be read, or any check fails twice, or a model call fails | `guard_reply` sends the fallback |

Claims cover the policy's variables only. A reply can still promise something the policy has no variable for (a
callback, a payment method); catch those with the core's domain rules (`forbid`, `only_entities`).

Readers can be combined (`effects.consensus`): `AgreeingFacts(jev, llm)` keeps only facts both found,
`AgreeingAnswers(a, b)` accepts an answer only if both read the same value, and `UnionClaims(a, b)` checks every claim
either found. If one of the two fails, the other's result is used alone (as with a single reader) and a WARNING is
logged on `policyproof.consensus`.

Quotes are matched on letters and digits a to z and 0 to 9 (the core's `normalize`), so text in other scripts
(Chinese, Cyrillic, Arabic, ...) can't be quoted yet: every answer reads as unclear and every reply falls back.

A `Compiled` policy holds a Z3 context: use it from one thread (any number of turns on one event loop is fine).

## Development

```bash
uv sync
uv run ruff check . && uv run ty check && uv run lint-imports && uv run pytest
PP_BEDROCK_MODEL=... TYPESAFE_API_KEY=... uv run pytest -m live   # real models; each test skips without its credentials
PP_UPDATE_SNAPSHOTS=1 uv run pytest tests/unit/test_prompts.py     # after an intended prompt change
uv run pytest --hypothesis-profile=ci     # the laws with 1000 examples each (about 8 minutes)
uv run python -m policyproof.schema       # regenerate policy.schema.json after changing the schema builder
```

Licensed under Apache-2.0.
