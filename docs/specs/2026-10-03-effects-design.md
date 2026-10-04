# policyproof, milestone 2: the effects layer

*2026-10-03. Design spec for review. Builds on the milestone 1 core (`docs/specs/2026-10-03-core-design.md`), the
demo's `decision/answer_check.py` and handler loop, the lab's Jev V5 runs, and a throwaway pydantic-ai spike (results
below).*

## Purpose

Milestone 1 decides and checks, given facts and claims. Milestone 2 gets those facts and claims out of text, using
any LLM provider and, optionally, Jev. It then wraps a conversation turn in two pipelines:

- **`read_turn`:** turns a customer message into facts and a decision.
- **`guard_reply`:** never lets an unchecked reply reach the customer.

Its job is reliability. When a model is wrong, unavailable or unsure, the result must fail toward asking again or
sending a safe fallback, never toward a wrong decision or an unchecked claim.

Out of scope here (milestone 3 and later):
- the evaluation harness
- tuning Jev (option phrasings, number words)
- LangExtract authoring
- the Bedrock Automated Reasoning adapter
- migrating the demo

## Decisions

- **Async only.** Every effectful function is `async`; there is no sync API. Bedrock's sync client runs off the
  event loop inside pydantic-ai.
- **pydantic-ai behind our own ports.** Translators, guards and pipelines depend on small `Protocol`s of our own.
  pydantic-ai (`pydantic-ai-slim`) is the only implementation we ship, for chat models (any provider it supports)
  and for Jev (`TypeSafeModel`). Only `effects.llm` and `effects.jev` import it.
- **Guards are pure and live in their own package.** The demo's checks become total functions over plain data, in
  `policyproof.guards` (which imports only `core`). The LLM readers run them inside pydantic-ai's output validator,
  so one rejection becomes one retry. They run again on the final output.
- **Jev for facts, an LLM for claims.** Jev answers per-variable choices with confidences but no quotes, so it is
  used for facts and answers only. Claims are expression trees and need an LLM.
- **Fail closed.** Each pipeline step errs toward more questions or the fallback text, never toward accepting more
  (see Errors).
- **Style unchanged from milestone 1:**
  - frozen, slotted dataclasses and closed unions, with `match` and `assert_never`;
  - `returns` `Result` only;
  - ty, uv, ruff, Hypothesis;
  - Python >=3.13.

## Spike results (pydantic-ai-slim 2.54, ty 0.0.84, Bedrock, 2026-10-03)

| Question | Finding |
|---|---|
| Can it return our recursive expression schema? | `StructuredDict` refuses recursive `$defs`. Unrolling the schema is unusable: 1.3 MB at depth 3, 19 MB at depth 4. **Recursive pydantic models** mirroring the grammar (4.5 KB of schema) worked live on Sonnet 4.5 and Haiku 4.5, in one request each. |
| Capped retry | `retries={"output": N}` with `ModelRetry` makes at most N+1 requests; when retries run out it raises `UnexpectedModelBehavior`. Our `DecodeError` text is sent back word for word. |
| Vacuous claims | Haiku emitted bare `true` claims. A guard requiring at least one variable, plus one retry, fixed this in both live runs. |
| Jev | `TypeSafeModel` with a `create_model` of `Choices({...})` fields sends one choice per field, with options described, which is the lab's V5 shape. `provider_details` carries `confidence` and `probabilities` per field. |
| ty | Clean on the adapter shape; it reported all 5 planted errors, including a missing case at `assert_never` and a validator for the wrong output type. No false positives. |
| Size | Core: 5 packages, 54 MB. With `[bedrock]`: 28 packages, 106 MB. With all providers plus `typesafe`: 40 packages, 140 MB. Import takes about 0.23 s. |
| Annoyance | It prints a promotional banner to stdout unless `PYDANTIC_AI_NO_BANNER=1` is set. |

## Package layout

```
policyproof/
  core/            milestone 1, plus the `Volunteered` change below
  guards/          pure; imports core only
    answer.py        check a raw answer to the pending question
    facts.py         check raw volunteered facts
    claims.py        check raw claims
    robust.py        decide_robustly: the Z3 re-check of weak facts
  effects/
    errors.py        LLMError
    ports.py         raw types and the four Protocols
    consensus.py     AgreeingFacts, AgreeingAnswers, UnionClaims
    pipeline.py      read_turn, guard_reply, template
    llm/             [llm] extra
      exprmodel.py     the expression grammar as recursive pydantic models
      prompts.py       pure prompt builders
      readers.py       LLMReaders: all four ports
    jev/             [jev] extra
      readers.py       JevReaders: FactReader and AnswerReader
```

**Import contracts (import-linter, in CI):**
- `core` imports nothing of ours (unchanged).
- `guards` imports only `core`.
- `effects.ports`, `effects.consensus` and `effects.pipeline` import `core`, `guards` and `effects.errors`/`ports`.
  They never import pydantic or pydantic-ai.
- `effects.llm` and `effects.jev` don't import each other.
- pydantic-ai is imported only under `effects.llm` and `effects.jev`.

**Extras:**
- `[llm]` = `pydantic-ai-slim>=2.54`. Users add their provider (e.g. `pydantic-ai-slim[bedrock]`) themselves, and the
  README says so.
- `[jev]` = `pydantic-ai-slim[typesafe]>=2.54`.
- The empty `anthropic`, `bedrock` and `openai` extras are removed. `extract` and `bedrock-ar` stay for later
  milestones.

**Other conventions:**
- Models are passed in as values; the library never reads the environment or holds a global client.
- `effects.llm` and `effects.jev` call `os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")` on import.
- A `Compiled` must not be shared across threads (this goes in the docstring and README). Concurrent use within one
  event loop is fine.

## Core change: evidence for volunteered facts

`core.facts.Volunteered(quote: str)` becomes `Volunteered(evidence: Evidence)`:

```python
@dataclass(frozen=True, slots=True)
class Quoted:
    text: str             # exact span of the message

@dataclass(frozen=True, slots=True)
class Scored:
    confidence: float     # 0..1, from a reader that can't quote (Jev)

type Evidence = Quoted | Scored
```

`rank`, `merge`, firmness and `decide` are unchanged: a volunteered fact is firm unless its variable has
`confirm_volunteered`. Existing tests and the demo parity test are updated to `Volunteered(Quoted("..."))`.

## Errors

```python
type LLMError = Unavailable | Malformed | Refused   # each a frozen dataclass with `message: str`
```

| Error | When |
|---|---|
| `Unavailable` | Network failure, throttling, authentication, or a 5xx (`ModelAPIError`, `ModelHTTPError`). |
| `Malformed` | Retries ran out (`UnexpectedModelBehavior`), or the final output failed its guard. |
| `Refused` | The model declined or a content filter fired, or Jev handed off (`DecisionHandOff`, including `UnsureRoute` and `UnfillableRoute`). |

Any other exception is a bug in our code or a misconfiguration, and propagates. A guard rejecting an item is **not**
an error: it shows up as an `Unclear` reading or as an entry in a `rejected` list.

## Ports (`effects/ports.py`)

```python
@dataclass(frozen=True, slots=True)
class Said:            # the message answers the question
    value: object          # plain data; the guard checks it against the variable's sort
    quote: str

@dataclass(frozen=True, slots=True)
class Unclear:         # it tries to answer, but can't be read
    reason: str

@dataclass(frozen=True, slots=True)
class NotAnswered: ...

type RawAnswer = Said | Unclear | NotAnswered

@dataclass(frozen=True, slots=True)
class RawFact:
    var: str
    value: object
    evidence: Evidence

@dataclass(frozen=True, slots=True)
class RawClaim:
    expr: object           # plain data in the YAML expression shape
    quote: str

class AnswerReader(Protocol):
    async def read_answer(self, p: CheckedPolicy, var: str, message: str) -> Result[RawAnswer, LLMError]: ...

class FactReader(Protocol):
    async def read_facts(self, p: CheckedPolicy, message: str) -> Result[tuple[RawFact, ...], LLMError]: ...

class ClaimReader(Protocol):
    async def read_claims(self, p: CheckedPolicy, reply: str) -> Result[tuple[RawClaim, ...], LLMError]: ...

class Rewriter(Protocol):
    async def rewrite(self, draft: str, problems: tuple[Problem, ...], instructions: str
                      ) -> Result[str, LLMError]: ...
```

`value` is plain data (`bool`, `int`, `str`, or `{"real": "2.5"}`) because readers mustn't build core literals; the
guards decode it.

## Guards (`policyproof.guards`)

Each guard is total and pure. It returns what it kept and, where it can drop items, what it rejected and why:
`Rejected(item: str, reason: str)`, with `item` being the variable name or the claim's quote.

**`answer.check(p, var, message, raw: RawAnswer) -> Answer | Unclear | NotAnswered`**, where
`Answer(fact: Fact)` carries `Answered(question, quote)` provenance.

These are the demo's rules:
1. If `var` isn't an `ask` variable, the result is `Unclear("not an askable variable")`. This is a caller bug, but
   the guard stays total.
2. `Said.quote` must be a non-empty substring of `message`, compared case-sensitively after collapsing whitespace.
   Otherwise the result is `Unclear("quote not in message")`.
3. `Said.value` must decode to a literal of the variable's sort, else `Unclear`.
4. For a Bool variable: if the message opens with a yes-word (`yes`, `yeah`, `yep`, `sure`, `correct`, `that's right`)
   and the value is false, or with a no-word (`no`, `nope`, `not really`) and the value is true, the result is
   `Unclear("opening contradicts answer")`. These are the demo's word lists, matched case-insensitively on the first
   clause.
5. `Unclear` and `NotAnswered` pass through unchanged.

**`facts.check(p, message, raws, *, min_confidence=0.5) -> tuple[Facts, tuple[Rejected, ...]]`**

A raw fact is kept as `Fact(var, lit, Volunteered(evidence))` only if:
- its variable exists and isn't `derived`;
- its value decodes to the variable's sort;
- `Quoted` evidence is a non-empty substring of `message`, compared as above;
- `Scored` evidence has at least `min_confidence`.

Facts that are kept are combined with `core.facts.merge`. Two kept facts that conflict stay conflicting, so
`decide` reports the contradiction; this is milestone 1's semantics.

**`claims.check(p, reply, raws) -> tuple[tuple[Claim, ...], tuple[Rejected, ...]]`**

A raw claim is kept as `core.check.Claim(expr, quote)` only if:
- `expr` decodes with `codec.decode_expr` against the policy's signature;
- it type-checks as Bool;
- it has at least one free variable;
- `quote` is a non-empty substring of `reply`.

**`robust.decide_robustly(c, fs, *, unclear, firm_confidence=0.8) -> Decision`**

This is V5's Z3 re-check:
1. Let `weak` be the volunteered facts with `Scored` evidence below `firm_confidence`.
2. If `decide(c, fs)` is the same `Decision` as `decide(c, fs without weak)`, return it.
3. Otherwise return `NeedInfo(var, question, "confirm", what_if)` for the first weak variable in policy order that
   is used by the result decided with the weak facts (its `rules` and `facts_used`), or by the first weak variable
   otherwise.

A weak fact on a `system` variable can't arise: readers only produce volunteered facts, and system facts outrank
them.

## Consensus (`effects/consensus.py`)

Each combinator wraps two ports into one and runs both concurrently.

**`AgreeingFacts(a, b)`, a `FactReader`:**
- It keeps a `(var, value)` that both readers report.
- Evidence: if either side has `Quoted` evidence, the quote is kept (from `a` if both quote); otherwise the
  `Scored` evidence with the lower confidence is kept.
- A variable they disagree on, or that only one reports, is dropped. A `FactReader` returns facts only, so a
  disagreement is logged (see below) rather than returned.

**`AgreeingAnswers(a, b)`, an `AnswerReader`:**
- If both readers return `Said` with equal values, the result is `Said`, with the quote from the first quote that is
  in the message.
- If both return `NotAnswered`, the result is `NotAnswered`.
- Anything else is `Unclear("readers disagree")`.

**`UnionClaims(a, b)`, a `ClaimReader`:** the claims from both readers, with duplicates removed by `(expr, quote)`
equality.

**One side failing:** if only one side fails, the combinator returns the other side's result. If both fail, it
returns `a`'s error. Ports return only a `Result`, so a one-sided failure and a dropped disagreement are reported
through the standard `logging` module (logger `policyproof.consensus`, level WARNING), not in the return value.
`Turn.degraded` covers only errors that `read_turn` itself observes.

**Laws:**
- Each combinator is commutative, up to which side's evidence or quote is kept.
- Each is idempotent (`X(a, a)` is the same as `a`).
- `AgreeingFacts` never keeps more than either side kept.
- `UnionClaims` never keeps fewer.

## Pipelines (`effects/pipeline.py`)

```python
@dataclass(frozen=True, slots=True)
class Conversation:
    facts: Facts                       # includes system facts the caller loaded
    pending: NeedInfo | None           # the question asked last turn
    unclear: frozenset[str]

@dataclass(frozen=True, slots=True)
class Readers:
    answers: AnswerReader
    facts: FactReader

@dataclass(frozen=True, slots=True)
class Turn:
    state: Conversation                # the next turn's state; pending = decision if it's a NeedInfo
    decision: Decision
    answer: Answer | Unclear | NotAnswered | None   # None when nothing was pending
    rejected: tuple[Rejected, ...]
    degraded: tuple[LLMError, ...]

async def read_turn(c: Compiled, state: Conversation, message: str, r: Readers,
                    *, min_confidence: float = 0.5, firm_confidence: float = 0.8) -> Result[Turn, LLMError]
```

1. The answer to `state.pending` (if any) and the volunteered facts are read concurrently with `asyncio.gather`.
2. **Answer:**
   - a reader error makes the result `Failure(error)`, because the question can't move forward without its answer;
   - an `Answer` merges its fact and removes the variable from `unclear`;
   - `Unclear` adds the variable to `unclear`;
   - `NotAnswered` changes nothing.
3. **Facts:**
   - a reader error is recorded in `degraded`, and the turn goes ahead without volunteered facts;
   - otherwise `guards.facts.check` runs and the kept facts are merged into the state.
4. `decision = decide_robustly(c, facts, unclear=..., firm_confidence=...)`.

```python
@dataclass(frozen=True, slots=True)
class Guarded:
    text: str
    attempts: int                      # 1 or 2 drafts checked
    result: CheckResult | None         # the last check run, None if none could run
    fell_back: bool
    reason: str | None                 # why it fell back

async def guard_reply(c: Compiled, facts: Facts, decision: Decision, draft: str,
                      claims: ClaimReader, rewriter: Rewriter, *,
                      rules: tuple[ReplyRule, ...] = DEFAULT_RULES,
                      instructions: str = "",
                      fallback: Callable[[Decision], str] = template) -> Guarded
```

1. Read the draft's claims, run `guards.claims.check`, then `core.check.check_reply`. If the reply passes, return
   the draft.
2. Otherwise call `rewriter.rewrite(draft, problems, instructions)` and check the rewrite the same way. If it
   passes, return it with `attempts=2`.
3. Otherwise return `fallback(decision)` with `fell_back=True`.
4. Any reader or rewriter error also leads to the fallback, with `reason` set to the error.

`guard_reply` never raises an `LLMError` and never returns text that hasn't passed `check_reply`, except the
fallback.

Claims rejected by the guard count as problems: a reply whose claims can't be grounded fails the check, as in
milestone 1's fail-closed ruling.

`template(decision) -> str` is plain and deterministic. Depending on the decision it says one of:
- `Decided`: "Under the policy, the outcome is {outcome}."
- `NeedInfo`: the variable's question.
- `Contradiction`: "Some of the information conflicts; a person will review this."
- `Escalate`: "A person will review this."

## Implementations

### `effects.llm`

- **`LLMReaders(model: Model, *, retries: int = 1, rewrite_settings: ModelSettings = {"temperature": 0.3})`**
  implements all four ports with one `Agent` per call.
- **`prompts.py`** has pure builders: `answer_prompt(p, var)`, `facts_prompt(p)`, `claims_prompt(p)` and
  `rewrite_prompt(problems, instructions)`. They list the variables with their sorts, descriptions and enum values,
  and describe the expression shape. Snapshot tests on `toy.yaml` keep them stable.
- **Output types:**
  - **Answers:** `create_model` per variable: `status: Literal["answered", "unclear", "not_answered"]`,
    `value: <Literal of enum values> | bool | int | str | None`, `quote: str | None`, `reason: str | None`.
  - **Facts:** `list[{var: Literal[<non-derived names>], value: bool | int | str | Real, quote: str}]`.
  - **Claims:** `exprmodel.Claims`.
  - **Rewrites:** `str`.
- **Validation:** the output validator runs the matching guard. Any rejection, an `Unclear` reading, or a
  `rejected` entry raises `ModelRetry` with the reasons. After the run the guard runs again; a final output that
  still has rejections returns `Malformed`, except for answers, where `Unclear` is a valid result.
- **Exception mapping:** `UnexpectedModelBehavior` becomes `Malformed`; `ModelAPIError` (which includes
  `ModelHTTPError`) becomes `Unavailable`; a content-filter finish reason becomes `Refused`.
- **`exprmodel.py`:** one model per operator (`Not`, `And`, ..., `In`, `Real`), with aliases for `not`, `and`, `or`
  and `in`, `extra="forbid"`, and `type Expr = bool | int | str | Real | Not | ...`.

### `effects.jev`

- **`JevReaders(model: TypeSafeModel, *, min_confidence: float = 0.5)`** implements `FactReader` and `AnswerReader`.
- **Facts:**
  - `create_model` with one `Choices` field per non-derived Bool or Enum variable;
  - options are the variable's values (`"true"`/`"false"` for Bool) plus `not_stated`;
  - each option is described from the variable's description;
  - the field description is the variable's question, or its description for system variables.
  - Each answered field becomes a `RawFact` with `Scored(confidence)`, read from
    `provider_details["confidence"]`.
  - Int and Real variables are skipped (documented); `AgreeingFacts` with an LLM covers them.
- **Answers:**
  - one `Choices` over the variable's values plus `unclear` and `not_answered`;
  - the result is `Said(value, quote=message)`, because Jev can't point to a span (the guard's opening-word check
    still applies);
  - confidence below `min_confidence` gives `Unclear("low confidence")`.
- **Exception mapping:** a `DecisionHandOff` becomes `Refused`, and API errors are mapped as for `effects.llm`.

## Testing

- **Unit tests:**
  - `LLMReaders` with `FunctionModel`, one case each: valid output; a rejection fixed by the retry; retries running
    out (`Malformed`); a `ModelAPIError` (`Unavailable`).
  - `JevReaders` with a `TypeSafeModel` subclass that overrides `decide` and returns scripted answers. The spike
    showed this works. These tests also assert the exact questions that are sent.
  - Pipelines and consensus with fake ports: plain dataclasses that return scripted `Result`s.
- **Laws (Hypothesis, `tests/laws/`):**
  - E1: for every generated expression `e`, `exprmodel` validates `encode_expr(e)`, the dump equals it, and the
    published JSON Schema accepts it.
  - E2: the guards are sound. Every kept fact has a known non-derived variable, the right sort, and a quote in the
    message (or enough confidence). Every kept claim decodes, is Bool, has a free variable, and has its quote in the
    reply.
  - E3: the consensus laws above.
  - E4: `guard_reply` is total over fake ports with arbitrary success and failure scripts. It never raises, and its
    `text` is either a draft whose `CheckResult` passed or `fallback(decision)`.
  - E5: `decide_robustly` with no weak facts equals `decide`.
- **Parity:** the demo's `answer_check` test cases give the same readings through `guards.answer`.
- **Live tests** (`-m live`, skipped without credentials):
  - Bedrock Haiku 4.5 via `AWS_PROFILE`/`AWS_REGION`;
  - Jev via `TYPESAFE_API_KEY`, with `jev-1.13.0` pinned;
  - one `read_turn` and one `guard_reply` on `toy.yaml` each.
  - Not run in CI.
- **CI:** installs `[llm,jev]`, runs the new import contracts, and runs ty over `src` and `tests`.

## Deliverables beyond code

- **README:**
  - choosing models;
  - setting up the extras;
  - what fails closed and how;
  - not sharing `Compiled` across threads.
- **`examples/turn.py`:** one `read_turn` plus `guard_reply` on `toy.yaml`, with a Bedrock model passed in.
- **Housekeeping:** stop tracking the committed `__pycache__/` files and add them to `.gitignore`.

## Open points

- Whether the bare `real` sort can be asked of Jev as a Score; deferred.
- Per-value phrasings in the policy format for better Jev option descriptions: an M3 decision, made with the
  evaluation harness.

## Refinements from prototyping the plan (2026-10-04)

Decisions made while building the plan's prototype. Each is reflected in the plan (`docs/plans/2026-10-04-effects.md`).

- **The raw types live in `guards/raw.py`** and `effects.ports` re-exports them. The guards take them as input and
  may import only the core.
- **Quotes match after the core's `normalize`** (lowercase, punctuation collapsed), as whole words (`guards.values.
  in_text`), so `I’d` matches `I'd`. This replaces the case-sensitive matching above, so one rule holds everywhere.
- **The opening words are the demo's lists:** `yes|yeah|yep|yup|sure|correct|that's right|that is right` and
  `no|nope|nah|not really`, matched at the start of the message.
- **`literal_for`** reads Booleans from `true`/`false` strings too (Jev's options), enum values as `VALUE` or
  `Sort.VALUE` in any case when that is unambiguous, and reals from ints or `{"real": ...}`, never floats.
- **`decide_robustly`** compares what the two decisions conclude (the outcome, or the variable asked), not the whole
  `Decision`, so a weak fact that only appears in `facts_used` doesn't cause a confirmation. Weak facts that nobody
  can be asked about (volunteered facts about system variables, which the fact guard allows) are ignored: it decides
  without them. It and `template` also handle `InvalidFacts`.
- **Consensus compares values as policy literals,** so Jev's `"true"` agrees with an LLM's `True`. The pure functions
  (`agree_facts`, `agree_answers`) therefore take the policy. Two `Unclear` answers give the first one.
- **`guard_reply` turns rejected claims into problems** under the rule name `claims_readable`, so they reach the
  rewriter.
- **When retries run out, an LLM answer is `Unclear`, not `Malformed`,** so the question is asked again rather than
  the turn failing. Facts and claims stay `Malformed`.
- **The LLM output types are static models** (`value: bool | int | str | Real`), not built per variable; the guard
  and one retry enforce the variable's sort, and ty can check the code. Jev still builds its types per policy,
  because its questions come from them.
- **Jev's fields are named `f0`, `f1`, ... with the variable names as aliases,** so a variable named like a pydantic
  attribute (`model_config`) still works. A policy with nothing Jev can ask makes no call, and a number answer is
  `Refused`, so `AgreeingAnswers` uses the other reader.
- **Prompt examples use the policy's own variable names,** with `{"real": "2.5"}` for Real variables.
- **Tests run async code with `asyncio.run`;** no pytest-asyncio. Live tests need `PP_BEDROCK_MODEL` (an inference
  profile ID) and AWS credentials, or `TYPESAFE_API_KEY`, and are excluded from the default run.
- **`tests/policies/weights.yaml`** is the smallest policy with a Real variable, for the guard and prompt tests.
