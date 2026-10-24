# policyproof

Prove what an agent may decide and say, from a written policy.

An AI support agent that grants refunds, rebooks flights or approves returns is only as trustworthy as the policy
behind it, and a language model asked to "follow the policy" will sometimes decide the wrong outcome or promise
something the policy never allowed. `policyproof` takes those decisions away from the model. The policy is written as
rules that the [Z3](https://github.com/Z3Prover/z3) solver can reason about, and every decision is proved from them:

- **Decide, or ask the one question that settles it.** Given the facts you know about a customer, `policyproof`
  either proves the outcome (and names the rules and facts that prove it) or picks the single question whose answer
  would decide the case.
- **Check the policy itself.** Before anything runs, it finds rules that contradict each other and customers no rule
  decides, each shown as a concrete example customer.
- **Guard what the agent says.** Models read the customer's messages and draft the replies, but every claim in a
  drafted reply is checked against the proof before it is sent, and anything that can't be checked falls back to a
  plain safe reply.
- **Start from the document you already have.** The authoring layer turns a markdown policy into rules, and the
  studio, a local web page, lets the person who owns the policy fix contradictions and gaps in plain English, without
  reading logic.

The core is pure and deterministic: no LLMs, no network, no I/O. Models are optional and only ever read text.

> **Status:** early (0.1, pre-release). The API may still change.

## Getting started

`policyproof` needs Python 3.13 or later.

```bash
uv add "policyproof @ git+https://github.com/javergar/policyproof"
# or: pip install "policyproof @ git+https://github.com/javergar/policyproof"
```

### 1. Write a policy

A policy is a YAML file: typed variables (known from a system, asked of the customer, or derived by the rules), rules,
and the outcomes a case can end in. Save this as `refunds.yaml`:

```yaml
policy: late-parcels
version: "1"
variables:
  daysLate: { sort: Int, role: system, description: Days the parcel arrived after the promised date. }
  wantsRefund:
    sort: Bool
    role: ask
    question: Would you like your money back?
    description: The customer wants a refund rather than a voucher.
  refund: { sort: Bool, role: derived, description: The customer gets a refund. }
  voucher: { sort: Bool, role: derived, description: The customer gets a voucher. }
rules:
  - { id: R1, when: { and: [{ ge: [daysLate, 2] }, wantsRefund] }, then: refund }
  - { id: R2, when: { and: [{ ge: [daysLate, 2] }, { not: wantsRefund }] }, then: voucher }
  - { id: R3, when: { lt: [daysLate, 2] }, then: { and: [{ not: refund }, { not: voucher }] } }
  - { id: R4, when: refund, then: { not: voucher } }
  - { id: R5, constraint: { ge: [daysLate, 0] } }
outcomes:
  refund: { refund: true }
  voucher: { voucher: true }
  nothing: { refund: false, voucher: false }
```

[`policy.schema.json`](src/policyproof/schema/policy.schema.json) is its JSON Schema, for completion in your editor.

### 2. Decide a case

```python
from pathlib import Path

from policyproof.core.codec import from_yaml
from policyproof.core.decide import decide
from policyproof.core.facts import Answered, Fact, FromSystem, facts
from policyproof.core.solver import compile
from policyproof.core.syntax import BoolLit, IntLit
from policyproof.core.validate import gate

policy = from_yaml(Path("refunds.yaml").read_text()).unwrap()
compiled = gate(compile(policy)).unwrap()   # fails if the policy has errors

late = Fact("daysLate", IntLit(3), FromSystem("tracking"))
print(decide(compiled, facts(late)))
# NeedInfo(var='wantsRefund', question='Would you like your money back?', reason='missing',
#          what_if=((BoolLit(value=True), 'refund'), (BoolLit(value=False), 'voucher')))

yes = Fact("wantsRefund", BoolLit(True), Answered("Would you like your money back?", "yes please"))
print(decide(compiled, facts(late, yes)))
# Decided(outcome='refund', rules=('R1',), facts_used=(...))
```

With only the delivery date known, the case can't be decided yet, so `decide` returns the one question to ask and
what each answer would lead to. Once the customer answers, it proves the refund and names rule R1 as the reason.

### 3. Catch a contradiction

Add a rule that clashes with R1, say `{ id: R6, when: { ge: [daysLate, 10] }, then: { not: refund } }`, and `gate`
refuses the policy, showing the customer the rules can't agree on:

```text
<Failure: (NotTotal(witness={'daysLate': IntLit(value=10), 'wantsRefund': BoolLit(value=True)}), ...)>
```

A parcel 10 days late whose customer wants their money back has no possible outcome: R1 says refund, R6 says no
refund.

### 4. Try the studio

The studio is where a policy author fixes problems like that one in plain English. Try it with no model and no
account, using a sample policy and scripted stand-ins for the model (the Z3 checks are real):

```bash
git clone https://github.com/javergar/policyproof && cd policyproof
uv sync
uv run python scripts/studio_demo.py
```

### Where next

- [Reading text](#reading-text-policyproofeffects): read customer messages and guard drafted replies with a model.
- [Evaluating a configuration](#evaluating-a-configuration-policyproof-eval): check your readers on your policy
  before deploying.
- [Authoring a policy from a document](#authoring-a-policy-from-a-document-policyproofauthoring) and
  [the studio](#the-studio-policyproof-studio): start from a markdown policy.
- [`tests/policies/`](tests/policies) has larger reference policies (deliveries, retail refunds, flight
  disruption), and [`examples/`](examples) has their markdown documents, eval cases and a whole agent turn.

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
fix what's wrong with it, without reading logic. `policyproof studio` (below) puts it in front of the author.

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

## The studio: `policyproof studio`

A local page for the person who owns the policy: an operations, service or legal author who has never read a formula.

```bash
pip install 'policyproof[studio]'
policyproof studio delivery-refunds.md --model bedrock:us.anthropic.claude-sonnet-4-5-20250929-v1:0
```

The document sits on the left. On the right is the next thing to decide, always as an example customer in plain
words: what each rule involved says for them, quoted from the document, and one question ("What should this customer
get?"). The author answers; the studio proposes the smallest change to the document's sentences, Z3 checks it against
every rule and every approved example customer, and the author accepts it, rewords it ("Edit the wording" is checked
as they type) or chooses differently. Problems that share a rule are decided together, a change that causes a new
problem says so, and every accept is written to disk straight away and can be undone. Every validator finding is
shown the same way: contradictions, customers no rule decides, sentences nothing was taken from, two names for one
thing, outcomes nobody can get. Warnings can be dismissed with a reason, which is kept; they come back with it if the
rules involved change. When the document is edited in another editor, "Extract again" shows each sentence that now
reads differently and lets the author keep their fix or take the new reading.

Next to `delivery-refunds.md` it keeps `delivery-refunds.policy.yaml`, `delivery-refunds.examples.yaml` (the approved
example customers, each with facts that prove its outcome) and a `.delivery-refunds.studio/` folder (links from rules
to sentences, dismissals and their reasons, the undo history). All plain text, ready for git. The server listens on
127.0.0.1 only and needs the token in the link it prints. Without `--model` it opens a document that already has a
policy and offers everything that needs no model.

`uv run python scripts/studio_demo.py` tries it with no model at all: the couriers policy from the design, with
scripted stand-ins for the drafter and extractor and real Z3 checks.

## Development

```bash
uv sync
uv run ruff check . && uv run ty check && uv run lint-imports && uv run pytest
PP_BEDROCK_MODEL=... TYPESAFE_API_KEY=... uv run pytest -m live   # real models; each test skips without its credentials
PP_UPDATE_SNAPSHOTS=1 uv run pytest tests/unit/test_prompts.py     # after an intended prompt change
uv run pytest --hypothesis-profile=ci     # the laws with 1000 examples each (about 8 minutes)
uv run python -m policyproof.schema       # regenerate policy.schema.json after changing the schema builder
uv run python -m policyproof.studio.schema  # regenerate the studio API's schema after changing studio/wire.py
```

The studio's page is TypeScript (React, with an Elm-style update loop) under `studio/`; the built page ships inside
the package, so only its developers need Node:

```bash
cd studio && npm install
npm run codegen      # the page's types, from the two JSON Schemas
npm test && npm run typecheck
npm run build        # into src/policyproof/studio/static/, which is committed
```

Licensed under Apache-2.0.
