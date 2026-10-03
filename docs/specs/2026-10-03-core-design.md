# policyproof, milestone 1: the reliability core

*2026-10-03. Design spec for review. Builds on the AgentCore disruption demo (`decision/core.py`,
`answer_check.py`) and the policy-reasoning-lab spikes (`lab/localar.py`, `interactive.py`).*

## Purpose

`policyproof` is an open-source library for agents that must not contradict a written policy. Milestone 1 is the
**deterministic core**. It contains no LLM calls, no network access and no provider code. Given a policy and some facts,
it answers four questions:

1. **Is the policy sound?** (validation, used as a release gate)
2. **What does it decide?** Either a proven outcome, or the single question that settles it.
3. **Is this claim proven, refuted, or neither?** (answer checks)
4. **Why?** Which rules and facts were used, and where each fact came from.

LLM providers, the Jev translator, LangExtract authoring and the Bedrock adapter come in later milestones, behind
protocols. The core never imports them.

## Design rules

- **Our own format.** Policies are a typed syntax tree. Authors write YAML with infix rules, which is parsed into the
  tree. Z3 and SMT-LIB are compile targets only. There is no Bedrock format in the core.
- **OCaml-style Python:**
  - Closed unions of frozen, slotted dataclasses (PEP 695 `type`).
  - `match … case _: assert_never(x)` for exhaustiveness.
  - Modules of pure functions; no methods with behaviour beyond trivial accessors.
  - `Protocol`s as signatures, and dependencies passed as arguments.
  - No higher-kinded types and no `flow`/`pipe`/`curry`/`RequiresContext`.
- **Errors are values, using `returns` containers:**
  - `Result`, `Success`, `Failure`, `Maybe`, `@safe`.
  - Results are consumed with `.map`, `.bind`, `.alt`, `.lash` and `.value_or`.
  - A `match` on a `Result` happens only at the edges. It ends in `case _: unreachable()`, because neither ty nor mypy
    can prove `Success | Failure` exhaustive (spike, 2026-10-03).
  - Our own unions (syntax, errors, decisions, findings) are always matched exhaustively.
- **Pure core.** Z3 is wrapped so that each call builds its own `Context` and solver and returns plain values, so it is
  referentially transparent from outside. An import-linter contract forbids `policyproof.core` from importing
  `policyproof.effects` or any SDK.
- **Equational reasoning.** Every important function has stated laws, tested with Hypothesis. Where the domain is
  finite, they are also checked against a brute-force oracle.
- **Python ≥ 3.13.** Modules that define recursive types start with `from __future__ import annotations`, which is
  needed on 3.13; the spike confirmed ty is clean and the code runs. Development uses 3.14.
- **Tooling:** uv, ty, ruff, pytest, Hypothesis, import-linter.
- **Runtime dependencies:** `z3-solver`, `returns`, `pyyaml`.

## The policy format

```yaml
policy: flight-disruption
version: "1.0"

sorts:
  FareType: [LITE, CHOICE, FLEX]
  DisruptionType: [CANCELLED, DELAYED, ON_TIME]
  DisruptionCause: [CREW, ENGINEERING, SCHEDULING, IT_SYSTEMS, WEATHER, AIR_TRAFFIC_CONTROL, AIRPORT_SECURITY, NONE]

variables:
  fareType:        { sort: FareType, role: system, description: The fare type of the booking. }
  delayHours:      { sort: Int, role: system, description: Hours the flight is delayed (0 if not delayed). }
  wantsToTravel:
    sort: Bool
    role: ask
    question: Do you still want to take this trip?
    confirm_volunteered: true
    description: True if the customer still wants to travel; false if they choose not to and want to cancel.
  isSignificantlyDisrupted: { sort: Bool, role: derived, description: Cancelled, or delayed 3 hours or more. }
  isEligibleForRefund:      { sort: Bool, role: derived, description: Entitled to a full refund. }

rules:
  - id: R1
    source: rule 1
    define: isSignificantlyDisrupted := disruption == CANCELLED or (disruption == DELAYED and delayHours >= 3)
  - id: R3
    source: rule 3
    when: isSignificantlyDisrupted and isWithinAirlineControl and not wantsToTravel and not hasFlown
    then: isEligibleForRefund
    explain: Significantly disrupted within our control, and the customer chooses not to travel. Full refund.
  - id: RANGE1
    constraint: delayHours >= 0
    explain: A delay is never negative.

outcomes:                       # tried in order; each one is a conjunction of literals
  full_refund:     { isEligibleForRefund: true }
  travel_credit:   { isEligibleForTravelCredit: true }
  free_rebooking:  { isEligibleForFreeRebooking: true }
  no_refund_or_credit: { isEligibleForRefund: false, isEligibleForTravelCredit: false }
```

- **Rule kinds are explicit.** There are three:
  - `when`/`then`: an implication, the normal case.
  - `define` (`x := e`): if and only if. Definitions are intended, but they are still listed for review.
  - `constraint`: a bare assertion. It is allowed, but it is always reported.

  This replaces the string heuristics that guessed which rules were bare assertions or definitions
  (`core.py:271`, `localar.validate`).
- **Roles.**
  - `system`: comes from airline or other systems and is never asked.
  - `ask`: has a `question`; `confirm_volunteered` defaults to true.
  - `derived`: defined by rules.
- **Outcomes are data.** They replace the hard-coded `VERDICTS`, `REFUND` and the other constants (`core.py:25-33`).
- **Infix grammar** (a hand-written Pratt parser, no dependency). Precedence, lowest first:
  1. `<=>`
  2. `=>` (right-associative)
  3. `or`
  4. `and`
  5. `not`
  6. comparisons: `== != < <= > >=` and `x in {A, B}`
  7. `+ -`
  8. `*`
  9. atoms: identifiers, integers, decimals, `true`/`false`, parentheses

  Enum values may be bare (`CANCELLED`) when the name is unambiguous, or qualified (`DisruptionType.CANCELLED`).
  Decimals are exact (`Fraction`).

## Modules (`src/policyproof/core/`)

| Module | Main types and functions | Notes |
|---|---|---|
| `syntax.py` | `Sort = BoolSort \| IntSort \| RealSort \| EnumSort`. `Expr = Lit \| Var \| Not \| And \| Or \| Implies \| Iff \| Eq \| Cmp \| Arith \| In`. `Rule = When \| Define \| Constraint` (each with an id, a source and an explanation). `Variable`, `Role = System \| Ask \| Derived`, `Outcome`, `Policy`. | Only data. `And`/`Or`/`Arith` hold tuples. |
| `typecheck.py` | `sort_of(sig, e) -> Result[Sort, SortError]`, `check_policy(raw) -> Result[Policy, tuple[SortError, ...]]` | A smart constructor: a `Policy` value is always well formed. |
| `text.py` | `parse_expr(sig, s) -> Result[Expr, ParseError]` (the error carries a position and what was expected), `pretty(e) -> str` | |
| `codec.py` | `decode(data: Mapping) -> Result[Policy, DecodeError]`, `encode(p) -> dict`, `from_yaml(text)`, `to_yaml(p)` | Works on strings only. Reading files belongs to effects. |
| `semantics.py` | `evaluate(e, env) -> Result[Value, EvalError]`, `substitute(e, env)`, `free_vars(e)`, `simplify(e)` | The reference semantics. It is independent of Z3, and the laws are stated against it. |
| `solver.py` | `compile(p) -> Compiled`, `check(compiled, assumptions) -> SatResult = Sat(model) \| Unsat(core) \| Unknown(reason)`, `to_smtlib(p)` | The only module that imports z3. Unsat cores are mapped back to rule ids and fact labels. |
| `prove.py` | `classify(p, facts, claim) -> Proven(core) \| Refuted(core) \| Contingent(when_true, when_false) \| Inconsistent(core)`, `entails`, `equivalent` | Comes from `answer_check.classify_claim` and `localar.classify`. |
| `facts.py` | `Fact(var, value, provenance)`, `Provenance = System(source) \| Answer(question, quote) \| Volunteered(quote)`, `merge(a, b)` | Precedence is System > Answer > Volunteered. |
| `decide.py` | `decide(p, facts, asked) -> Decided(outcome, rules, facts_used) \| NeedInfo(var, question, reason) \| Contradiction(core) \| Escalate(reason)`, `next_question(p, facts)` | Generic over Bool and Enum variables that can be asked. An Int that can be asked is chosen only when it is the last unknown. A decision that depends on a volunteered fact first asks for confirmation. |
| `explain.py` | `Trace`: facts with provenance, rule steps in policy order, the query, the what-if table | Comes from `core.explain_*`. Wording and user-interface strings stay outside the core. |
| `validate.py` | `validate(p) -> Report`. `Finding = Conflict \| NotTotal(witness) \| ConstraintRule \| DefinitionToReview \| UnusedVariable \| NearDuplicate \| UnreachableOutcome \| UnreachableEnumValue \| DisjointGroups`, each with a `Severity`. `gate(report) -> Result[Policy, Report]` | Merges `core.validate` (including totality) with `localar.validate`. |
| `check.py` | `Claim(expr, quote)`. `check_reply(p, decision, reply, claims, rules) -> CheckResult`. `ReplyRule` is a plain function `(CheckInput) -> tuple[Problem, ...]`. Built-in rules: `grounded`, `classified`, `states_outcome`, `asks_open_question_verbatim_and_last`, `single_yes_no_question`. Configurable rules: `forbid(pattern)`, `require_mention(pattern)`, `only_entities(pattern, allowed)`. | The airline-specific `EXTRAS`, `SOURCES` and flight-number rules become configuration in the demo. |

## Laws (Hypothesis)

Every law is tested over generated, well-typed expressions and policies (`strategies.py`).

| # | Law | Checked by |
|---|---|---|
| L1 | `parse_expr(sig, pretty(e)) == Success(e)` | Hypothesis |
| L2 | `decode(encode(p)) == Success(p)` and `from_yaml(to_yaml(p)) == Success(p)` | Hypothesis |
| L3 | `evaluate(substitute(e, σ), ρ) == evaluate(e, σ ∪ ρ)` | Hypothesis |
| L4 | `evaluate(simplify(e), ρ) == evaluate(e, ρ)`, and `equivalent(e, simplify(e))` | Hypothesis, then Z3 |
| L5 | **Compile soundness:** for every total environment ρ, Z3's value of `compile(e)` under ρ equals `evaluate(e, ρ)` | Hypothesis |
| L6 | **Typecheck soundness:** if `sort_of(e) = s`, then `evaluate(e, ρ)` never fails with a type mismatch and returns a value of sort `s` | Hypothesis |
| L7 | **Classify against an oracle:** on finite domains (Bool, enums, small Int ranges), `classify` agrees with enumerating every model | brute force |
| L8 | **Monotonicity:** if `decide(p, F) = Decided(o)` and G ⊇ F is consistent, then `decide(p, G) = Decided(o)` | Hypothesis |
| L9 | `merge` is associative, commutative and idempotent (a semilattice ordered by provenance) | Hypothesis |
| L10 | **Questions make progress:** for `NeedInfo(v)`, every answer to v leads to `Decided` or to a strictly smaller set of unknowns that still matter | Hypothesis plus the oracle |

## Fixtures and parity

- `tests/policies/toy.yaml`: a small policy for unit tests.
- `tests/policies/flight_disruption.yaml`: the demo's 15 rules translated by hand from `policy/build_policy.py`.
- `tests/policies/retail_refund.yaml`: the lab's refund policy, from `bedrock_policy_fixed_desc2.json`.
- **Planted defects**, which the validator must find:
  - the R4/R8 totality conflict
  - a bare assertion (the lab's `ItemCategory_OTHER` bug)
  - an if-and-only-if overstatement
  - a near-duplicate name, as in the chunk-drift bug
  - an outcome that can never be reached
- **Parity test** (skipped if `~/code/agentcore-disruption-demo` is absent): for every demo booking × every answer
  (none, true, false, volunteered), `policyproof.decide` must give the same outcome or question as the demo's
  `core.decide`, and validation must report the same conflicts.

## Repo layout

```
policyproof/
  pyproject.toml          # uv, requires-python >=3.13, extras declared but empty until later milestones
  .python-version         # 3.14
  src/policyproof/__init__.py
  src/policyproof/core/{syntax,typecheck,text,codec,semantics,solver,prove,facts,decide,explain,validate,check}.py
  src/policyproof/effects/__init__.py     # placeholder: llm, translate, jev, extract, bedrock_ar come later
  tests/{unit,laws,parity}/ , tests/policies/*.yaml , tests/strategies.py
  .importlinter            # core must not import effects or SDKs
  .github/workflows/ci.yml # uv; ruff, ty (3.13 and 3.14), pytest; matrix 3.13 and 3.14
  LICENSE                  # Apache-2.0 (to confirm)
```

## Out of scope for milestone 1

LLM clients and translators, Jev, LangExtract authoring, Bedrock import/export and checks, the evaluation harness,
and migrating the demo. Each of these is a later milestone, built on the protocols defined against this core.

## Open points

1. **Licence:** Apache-2.0 is proposed.
2. **Name:** `policyproof`. Check that it is free on PyPI before the first release.
