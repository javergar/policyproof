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

## Evaluating a configuration: `policyproof eval`

Before deploying, check that your readers are safe on your policy. Write cases next to it: a turn case gives the
known facts, the question pending and the customer's message, and says what must be decided; a reply case gives the
facts and a draft, and says whether the check must catch it.

```yaml
policy: policy.yaml
cases:
  - id: says-yes
    turn: {facts: {daysLate: 3}, asked: wantsRefund, message: "Yes please, I'd like my money back."}
    expect: {decision: refund, facts: {wantsRefund: true}}
  - id: voucher-draft-is-caught
    held_out: true
    reply: {facts: {daysLate: 3, wantsRefund: true}, draft: "You'll get a voucher."}
    expect: caught
```

Name your reader configurations (models are pydantic-ai model strings) and run them:

```bash
policyproof eval cases.yaml --readers readers.yaml --runs 3 --json report.json
```

Every case runs `--runs` times for each configuration. A run is **correct**, **conservative** (it asked again,
escalated, or fell back: safe but unhelpful) or **wrong** (it decided the wrong outcome, misread a fact, or let a bad
draft through), and a case is as bad as its worst run. The gate passes with zero wrong cases and at most
`--max-conservative` (10%) conservative ones, over all cases and over the held-out cases alone. Exit codes: 0 pass,
1 fail, 2 invalid input (checked before any model is called).

Write held-out cases last and don't tune against them. `examples/eval/` has cases for the three reference policies
and a `readers.yaml`. On Bedrock Claude Haiku 4.5 the toy and flight cases pass; the retail held-out case
`unopened-and-cracked` comes out conservative (the model finds "unopened, but the screen is cracked" contradictory
and asks again), which is what a failed gate looks like in practice.

Phrasings help readers recognise answers. Add them to a variable in the policy; they never change a decision:

```yaml
wantsRefund:
  sort: Bool
  role: ask
  question: Would you like your money back?
  phrasings: {true: [money back, a refund], false: [a voucher is fine]}
```

## Authoring a policy from a document: `policyproof.authoring`

Policies are usually written for people, in markdown. The authoring layer turns one into a policy and helps its author
fix what's wrong with it, without reading logic. A local studio on top of it comes next (milestone 5).

- **Extraction** (`authoring.llm.LLMExtractor`, any pydantic-ai model, `[extract]` extra): the whole document in one
  pass, every rule linked to the sentence it came from, and the sentences that gave no rule.
- **Problems** (`core.problems.problems`): every clash between rules and every customer no rule decides, each shown
  as a minimal example customer. A gap is also a warning in `validate` (`Undecided`).
- **Plain words** (`authoring.plain`): facts and outcomes through the policy's new `display` phrases ("Came by
  courier", "{} days late", "A refund").
- **Proposals** (`authoring.propose`): the author says what a customer should get; a model drafts the smallest change
  to the document, the changed sentences are extracted again with the policy's own names, and Z3 checks the result
  against every rule and every approved example customer before the author sees it.

`python -m policyproof.authoring.bench --model MODEL DOC CASES [NAMES]` scores an extractor on a document against a
hand-written policy and its eval cases. The reference documents are in `examples/authoring/`.

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
