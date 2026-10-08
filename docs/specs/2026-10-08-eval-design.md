# policyproof, milestone 3: the evaluation harness

*2026-10-08. Design spec for review. Builds on milestone 1 (`docs/specs/2026-10-03-core-design.md`), milestone 2
(`docs/specs/2026-10-03-effects-design.md`) and the policy-reasoning-lab's comparison runs (`lab/compare2.py`, V0–V5).*

## Purpose

A user with their own policy needs to know, before deploying, whether a reader configuration (which models read
answers, facts and claims; whether Jev and consensus are used; which confidence bars apply) is safe on their policy.
Milestone 3 gives them `policyproof eval`. They write cases in YAML next to the policy, and the harness runs every
case several times through milestone 2's pipelines for each named reader configuration. It grades each run and gates
the deployment on **zero wrong cases**. The harness ships in the package, with a Python API and a CLI.

It also carries the one Jev tuning step from the lab that transfers cleanly: per-value **phrasings** in the policy
format, so the harness can measure whether they help.

Out of scope:
- whole-conversation cases (a later milestone can add them as a list of turns);
- number words and message paraphrasing (lab V5's other steps);
- token and cost accounting (not visible through the ports);
- recording or replaying model responses;
- LangExtract authoring and the Bedrock adapter.

## Decisions

- **For library users.** It ships in the package; the repo uses it on its own reference policies only as examples.
- **Two kinds of case, matching the two pipelines:** turn cases (`read_turn`) and reply cases (`guard_reply`). A
  failure points at one step.
- **Three grades, ordered by harm:** correct, conservative and wrong. Asking again, escalating, a reader error or a
  fallback is conservative, never wrong. The gate: zero wrong cases, and a conservative rate at or below a maximum.
- **A Python API first,** plus a CLI with a small reader configuration file built on pydantic-ai model strings.
- **Phrasings** are an optional field in the policy format, used by the Jev and LLM readers.
- **Style unchanged:** frozen dataclasses, closed unions with `assert_never`, `returns` `Result`, ty, uv; pure modules
  where possible.

## Package layout

```
policyproof/eval/
  cases.py    case types; decode a case file into Result[CaseFile, CaseError] with paths       pure (core only)
  grade.py    grade a run against its case                                                   pure (core only)
  report.py   Report, totals, held-out totals, gate, text and JSON rendering                pure (core only)
  run.py      async evaluate(...) -> Report, through the M2 pipelines                       effects, no SDK
  config.py   readers.yaml -> named configurations of M2 readers                            imports effects.llm/.jev
  cli.py      `policyproof eval` (argparse); `[project.scripts] policyproof = "policyproof.eval.cli:main"`
```

**Import contracts (import-linter):**
- `eval.cases`, `eval.grade` and `eval.report` import only `policyproof.core`.
- `eval.run` imports no pydantic, pydantic-ai or SDK.
- Only `eval.config` (and `eval.cli`, through it) import `effects.llm` and `effects.jev`.

**Extras:** `eval.config` needs `[llm]` (and `[jev]` for Jev). `policyproof eval` prints which extra to install when an
import is missing (exit code 2).

## The case file

```yaml
policy: toy.yaml                       # a path relative to this file
cases:
  - id: plain-yes                      # unique; [A-Za-z0-9_-]+
    turn:
      facts: {daysLate: 3}             # given facts (see below)
      asked: wantsRefund               # optional: the pending question (an `ask` variable)
      message: "Yes please, I'd like my money back."
    expect:
      decision: refund                 # an outcome name | {ask: <var>} | escalate
      facts: {wantsRefund: true}       # optional: facts that must be read, with these values
  - id: voucher-draft-is-caught
    held_out: true                     # optional, default false
    reply:
      facts: {daysLate: 3, wantsRefund: true}
      draft: "Since it was late, you'll get a voucher."
    expect: caught                     # caught | pass
```

**Given facts.**
- A `system` variable's fact is `FromSystem("case")`.
- An `ask` variable's fact is `Answered(<its question>, "case")`.
- A `derived` variable can't be given.
- Values use the policy's literal shapes and are decoded with `guards.values.literal_for`.

**A turn's pending question.** It is built as the core's `NeedInfo(var, question, "missing", what_if(...))` from the
given facts.

**Decoding.**
- `eval.cases.load(path) -> Result[CaseFile, CaseError]` reads the file, loads and checks the policy (with
  `codec.from_yaml`), and checks every case against it before anything else runs:
  - ids are unique;
  - variables, roles and values are valid;
  - `asked` is an `ask` variable;
  - expected outcomes exist;
  - an expected `ask` is an `ask` variable.
- `CaseError(path, message)` carries the YAML path (e.g. `cases[3].turn.facts.daysLate`).

```python
@dataclass(frozen=True, slots=True)
class TurnCase:
    id: str
    held_out: bool
    facts: Facts
    asked: str | None
    message: str
    expect: ExpectDecision          # Outcome(name) | Ask(var) | EscalateExpected()
    expect_facts: tuple[tuple[str, Lit], ...]

@dataclass(frozen=True, slots=True)
class ReplyCase:
    id: str
    held_out: bool
    facts: Facts
    draft: str
    expect: Literal["caught", "pass"]

type Case = TurnCase | ReplyCase

@dataclass(frozen=True, slots=True)
class CaseFile:
    policy: CheckedPolicy
    cases: tuple[Case, ...]
```

## Running

```python
@dataclass(frozen=True, slots=True)
class Configuration:          # in eval.run; built by eval.config or by hand
    name: str
    answers: AnswerReader
    facts: FactReader
    claims: ClaimReader
    rewriter: Rewriter
    min_confidence: float = 0.5
    firm_confidence: float = 0.8

async def evaluate(f: CaseFile, configurations: Sequence[Configuration], *, runs: int = 3,
                   concurrency: int = 4) -> Report
```

- The policy is compiled once.
- Every (configuration, case, run) is one job, with at most `concurrency` jobs in flight (`asyncio.Semaphore`).
- **A turn job** builds the `Conversation` (given facts, the pending question, nothing unclear), then calls `read_turn`.
- **A reply job** decides from the given facts with `core.decide`, then calls `guard_reply` with that decision.
- Each job records its result (`Turn`, `LLMError` or `Guarded`), its grade and its wall-clock seconds.
- An exception from a job is a bug in a reader: it is recorded as **wrong** with the reason `crashed: <type>: <message>`
  and the run goes on. A crash in a deployed reader would reach a customer, and nothing about it is safe.

## Grading (`eval.grade`, pure)

```python
type Grade = Correct | Conservative | Wrong      # Conservative(reason), Wrong(reason)
```

**Turn cases.** A failed turn (`Failure(LLMError)`) is conservative, with the reason `reader error: <describe(e)>`.
Otherwise the decision is graded:

| Expected | Got | Grade |
|---|---|---|
| outcome X | `Decided(X)` | correct |
| outcome X | `Decided(Y)` with Y ≠ X | **wrong** |
| outcome X | `NeedInfo`, `Escalate`, `Contradiction` | conservative |
| `{ask: v}` | `NeedInfo(v)` | correct |
| `{ask: v}` | `NeedInfo(w)` with w ≠ v, `Escalate`, `Contradiction` | conservative |
| `{ask: v}` | `Decided` | **wrong** |
| `escalate` | `Escalate`, `Contradiction` | correct |
| `escalate` | `Decided` | **wrong** |
| `escalate` | `NeedInfo` | conservative |
| anything | `InvalidFacts` | **wrong** (the guards should make it impossible) |

**Expected facts** are then checked against the turn's facts (`Turn.state.facts`):
- a fact read with a different value than expected is **wrong** (a misreading);
- an expected fact that wasn't read is conservative.

The worse grade of the decision and the facts is the run's grade.

**Reply cases** ("as written" means `not fell_back and attempts == 1`):

| Expected | Got | Grade |
|---|---|---|
| `caught` | not sent as written | correct |
| `caught` | sent as written | **wrong** |
| `pass` | sent as written | correct |
| `pass` | rewritten or fallback | conservative |

**A case's grade** is the worst over its runs: wrong over conservative over correct.

## Report and gate (`eval.report`, pure)

```python
@dataclass(frozen=True, slots=True)
class RunResult:
    run: int
    grade: Grade
    seconds: float
    trace: Trace          # TurnTrace | ReplyTrace | ErrorTrace: what is shown for a case that isn't correct

@dataclass(frozen=True, slots=True)
class CaseResult:
    case: str
    held_out: bool
    grade: Grade          # the worst over its runs
    runs: tuple[RunResult, ...]

@dataclass(frozen=True, slots=True)
class Totals:
    correct: int
    conservative: int
    wrong: int            # counts of cases

@dataclass(frozen=True, slots=True)
class ConfigurationResult:
    name: str
    cases: tuple[CaseResult, ...]
    totals: Totals
    held_out: Totals

@dataclass(frozen=True, slots=True)
class Report:
    policy: str
    runs: int
    configurations: tuple[ConfigurationResult, ...]
```

**What the traces show:**
- **A turn:** the decision, every fact read with its evidence, the rejected items, the answer reading, and `degraded`.
- **A reply:** the text sent, `attempts`, `fell_back`, `reason`, the claims with their statuses, and the problems.
- **An error:** the `LLMError`, or the crash.

**The gate.** `gate(r: ConfigurationResult, max_conservative: float = 0.1) -> GateResult` passes when there are zero
wrong cases and the conservative share of cases is at or below `max_conservative`, both over all cases and over the
held-out cases alone (a configuration with no held-out cases passes that half). The share uses an empty-safe ratio.

**Rendering:**
- `render_text(r)` produces the terminal output: one block per configuration, with totals, held-out totals, the gate
  verdict, then each case that isn't correct with its runs' traces.
- `to_json(r)` and `from_json(text) -> Result[Report, str]` round-trip (law V2).

## Reader configuration (`eval.config`)

```yaml
models:
  haiku: bedrock:au.anthropic.claude-haiku-4-5-20251001-v1:0     # any pydantic-ai model string
  jev: typesafe:jev-1.13.0
configurations:
  haiku-only: {answers: haiku, facts: haiku, claims: haiku, rewriter: haiku}
  jev-plus-haiku:
    answers: {agree: [jev, haiku]}
    facts: {agree: [jev, haiku]}
    claims: haiku
    rewriter: haiku
    min_confidence: 0.5
    firm_confidence: 0.8
```

- `load_config(path) -> Result[ConfigFile, ConfigError]` checks the whole file first:
  - names are known;
  - `agree` is used only for answers and facts, and `union` only for claims;
  - Jev models appear only in the answers and facts slots;
  - confidences are between 0 and 1.
- `build(config, models: Mapping[str, Model] | None = None) -> tuple[Configuration, ...]` builds the readers:
  - models are built with pydantic-ai's `infer_model`, unless `models` is passed (tests pass `FunctionModel`s);
  - a `TypeSafeModel` becomes `JevReaders`, and any other model becomes `LLMReaders`;
  - `{agree: [a, b]}` becomes `AgreeingFacts` or `AgreeingAnswers`, and `{union: [a, b]}` becomes `UnionClaims`.

## CLI

```
policyproof eval CASES --readers READERS [--only NAME ...] [--runs 3] [--concurrency 4]
                 [--max-conservative 0.1] [--json OUT]
```

| Exit code | Meaning |
|---|---|
| 0 | every selected configuration passes its gate |
| 1 | some configuration fails its gate |
| 2 | the case file, the policy or the reader configuration is invalid, or an extra is missing; no model is called |

## Phrasings (core change)

`Variable` gains `phrasings: tuple[tuple[Lit, tuple[str, ...]], ...] = ()`. In YAML:

```yaml
wantsRefund:
  sort: Bool
  role: ask
  question: Would you like your money back?
  description: True if the customer wants a refund rather than a voucher.
  phrasings:
    true: [money back, a refund, reimburse me]
    false: [a voucher is fine, store credit]
```

- **Checks:**
  - each key decodes to a value of the variable's sort (`check_policy` reports `UnknownValue` or `SortMismatch`);
  - each value is a non-empty list of non-empty strings;
  - a derived variable can't have phrasings (a new `BadPhrasings` sort error).
- **Formats:** the JSON Schema and `encode` are extended; law L1 (codec round-trip) covers them through the
  strategies.
- **Jev:** an option's description gains `e.g. "money back", "a refund"`.
- **LLM prompts:** the answer and facts prompts list them under the variable as `said as: ...`.
- Nothing else reads phrasings: they never change a decision.

## Testing

- **Unit tests:**
  - `eval.cases`: every decode error with its path, and a valid file;
  - `eval.grade`: one test per row of both tables, plus expected facts;
  - `eval.report`: totals, held-out totals, gate thresholds, empty held-out, text rendering (snapshot), JSON round-trip;
  - `eval.run`: end to end with M2's fake ports (turn and reply cases, concurrency respected, a crashing reader
    graded wrong);
  - `eval.config`: every validation error, and building with `FunctionModel`s and an offline `TypeSafeModel`;
  - `eval.cli`: exit codes 0, 1 and 2 with an injected model map;
  - phrasings: the codec, typecheck, prompts and Jev options.
- **Laws (Hypothesis):**
  - V1: the gate is monotone. Turning any run's grade worse never turns a failing gate into a passing one, and a
    case's grade is the worst of its runs.
  - V2: `from_json(to_json(r)) == Success(r)`.
- **Examples:** `examples/eval/` holds case files for `toy.yaml`, `flight_disruption.yaml` and `retail_refund.yaml`
  (about 10 to 20 cases each, with some held out), and a `readers.yaml` with a Bedrock Haiku configuration and a Jev
  consensus configuration. A test loads every example file without calling a model.
- **Live** (`-m live`): the toy cases with Bedrock Haiku pass the gate.

## Open points

- Whether held-out cases should be kept in a separate file so they can't be tuned against; for now it's a flag, and
  the README says to write them after tuning, as in the lab.
