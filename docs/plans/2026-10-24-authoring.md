# policyproof milestone 4 (the authoring layer): implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** the Python layer under `policyproof studio`: extract a policy from a markdown document sentence by
sentence, find every problem with its own example customer, phrase facts in plain words, and turn an author's answer
into a checked change to the document and its rules. Milestone 5 (the local server and the React UI) is planned
separately, on top of this.

**Architecture:** `core.problems` enumerates problems with Z3 (pure, in the core). `policyproof.authoring` has
pure modules (`document`, `plain`, `examples`, `merge`: the core and guards only), ports and the proposal loop with
no SDK (`ports`, `propose`), and the only modules that call models (`authoring.llm`). Everything model-facing is
tested with fakes; real models run only in `live` tests and the extractor benchmark.

**Tech Stack:** Python >= 3.13, uv, z3-solver, returns, PyYAML, pydantic-ai-slim 2.54+ (only in `authoring.llm`);
ty, ruff, pytest, Hypothesis, import-linter.

**Spec:** `docs/specs/2026-10-24-studio-design.md`, including "Calls made after the design review". Read it first;
the clickable prototype is `docs/specs/assets/2026-10-24-studio-prototype.html`.

## Left for milestone 5

The workspace files (links, dismissed findings with reasons, sentences marked background, undo history), file
watching, the question wording for each validator finding (spec table "Every kind of problem"), the local server and
the React UI. This milestone gives them every operation they call.

## Global Constraints

- `requires-python = ">=3.13"`; ruff line length 120; ty clean on `src` and `tests`; all import contracts kept.
- Style as before: frozen, slotted dataclasses; closed unions with `match` ending in `assert_never`; a
  `Success`/`Failure` match ends in `case _: unreachable()`; `returns` `Result` for every expected failure; no
  exception crosses a port.
- No new runtime dependency for the core. `[extract]` (declared, empty today) becomes
  `["pydantic-ai-slim>=2.54"]`. Only `policyproof.authoring.llm` imports pydantic or pydantic-ai.
- `gate` must not change for existing policies: the new `Undecided` finding is severity **warning**.
- Problems are judged on **complete inputs** and shown as a **minimal customer**; two clashes are distinct when their
  rule sets differ (spec, Calls 1).
- An approved example's facts must make `decide` return `Decided(that outcome)` (spec, Calls 2).
- Links from rules to sentences are **(section heading, sentence text, occurrence)** anchors; character offsets are
  recomputed, never stored (spec, Calls 4).
- Extraction reads the **whole document in one pass**; partial re-extraction passes the current policy as the
  vocabulary.
- **No paid model call without the user's go-ahead.** Live tests are marked `live`; the benchmark's run step (Task 10)
  waits for the user and states the number of calls.
- Tests call async code with `asyncio.run`.
- Every commit message ends with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

Inputs a person will meet that the spec doesn't name. Each has a test in the task that owns the code:

1. **An integer input in a clash** (`daysLate`): there are infinitely many witnesses with the same rule set.
   Enumeration must return that clash once and stop, not loop to the cap
   (`test_an_integer_input_gives_one_clash_per_rule_set`, Task 3).
2. **The solver gives up mid-enumeration:** the result says `complete=False` and carries a `GaveUp`. It never
   silently returns fewer problems (`test_solver_giving_up_is_reported`, Task 3).
3. **The same sentence twice:** in two sections, or twice in one section. Anchors stay distinct and an edit hits the
   right one (`test_duplicate_sentences_get_distinct_anchors`, Task 4).
4. **A drafted edit that points at a sentence that isn't there** (the model misquoted it): retried with the reason,
   then reported as `EditFailed`, never a crash (`test_a_misquoted_sentence_is_retried_then_reported`, Task 7).
5. **A partial extraction that uses an unknown name or breaks the types:** `merge` returns the sort errors and
   `propose` retries, instead of saving an ill-typed policy (`test_merge_rejects_an_ill_typed_part`, Task 6;
   `test_an_unmergeable_extraction_is_retried`, Task 7).

---

### Task 1: Display phrases in the policy format

**Files:**
- Modify: `src/policyproof/core/syntax.py`, `src/policyproof/core/typecheck.py`, `src/policyproof/core/codec.py`
- Modify: `src/policyproof/schema/__init__.py`, `src/policyproof/schema/policy.schema.json` (regenerated)
- Modify: `tests/strategies.py`
- Test: `tests/unit/test_display.py`; `tests/laws/test_codec_laws.py` covers it through the strategies

**Interfaces:**
- Consumes: M1's codec, typecheck and schema; M3's `phrasings` (follow its pattern exactly).
- Produces:
  - `syntax.ValuePhrases(phrases: tuple[tuple[Lit, str], ...])` and `syntax.Template(text: str)`;
    `type Display = ValuePhrases | Template`.
  - `Variable.display: Display | None = None` (last field); `Outcome.display: str | None = None` (last field).
  - `typecheck.BadDisplay(variable: str, message: str)`, a new `SortError`.
  - YAML: a Bool or enum variable takes `display: {<value>: <text>, ...}`; an Int or Real variable takes
    `display: "<text with one {}>"`; an outcome takes `display: <text>`.

- [ ] **Step 1: Write the failing tests** in `tests/unit/test_display.py`:
  - `test_display_round_trips`: a policy with `carrier: {display: {COURIER: "Came by courier", POST: "Came by
    post"}}`, `daysLate: {display: "{} days late"}`, `wantsRefund: {display: {true: "Asked for a refund", false:
    "Didn't ask for a refund"}}` and outcome `refund: {refund: true, display: "A refund"}` decodes to those values, and
    `from_yaml(to_yaml(p)) == Success(p)`.
  - `test_display_errors_are_sort_errors`: each is `Failure(IllTyped((BadDisplay(var, ...),)))`:
    - an unknown enum value as a key;
    - a template on a Bool variable;
    - a map on an Int variable;
    - a template without `{}`, or with two.
  - `test_outcome_display_needs_text`: `display: 3` on an outcome is a `DecodeError` at `outcomes.refund.display`.
  - `test_schema_has_display`: the regenerated schema accepts the round-trip policy and rejects
    `display: {NOPE: x}` only through the typecheck (the schema allows any string keys, like `phrasings`).
- [ ] **Step 2: Run** `uv run pytest tests/unit/test_display.py -q`. Expected: FAIL (unknown key `display`).
- [ ] **Step 3: Implement** the types, decode/encode (`_display(sort, t, path)` next to `_phrasings`), the typecheck,
  the schema, and `strategies.declarations()` drawing an optional display per variable and outcome.
- [ ] **Step 4: Run** `uv run pytest -q && uv run ty check && uv run ruff check && uv run lint-imports`. Expected:
  all pass, including the codec laws.
- [ ] **Step 5: Commit** `core: display phrases for variables and outcomes`.

---

### Task 2: Gaps in the solver and the validator

**Files:**
- Modify: `src/policyproof/core/solver.py`, `src/policyproof/core/validate.py`
- Create: `tests/policies/defects/gap.yaml`
- Modify: `tests/unit/test_validate.py`, `tests/unit/test_real_policies.py`, `tests/unit/test_solver.py`

**Interfaces:**
- Consumes: `solver.totality`, `validate._logical`.
- Produces:
  - `solver.totality(c, inputs, *, blocked: Sequence[frozenset[str]] = ()) -> SatResult`. Each blocked rule set
    adds "these rules can hold together for these inputs" (`Exists(others, And(rules))`), so a clash with that same
    rule set is never found again.
  - `solver.undecided(c, inputs, *, blocked: Sequence[Expr] = ()) -> SatResult`.
    - `Sat(witness over inputs)` when the input-only rules hold, the rest can hold (`Exists(others, rest)`), and for
      every outcome `o`, `Exists(others, And(rest, Not(o)))` holds.
    - Each blocked expression is asserted negated.
    - `Unsat` when there are no outcomes.
  - `solver.decidable(c, inputs, *, given: Sequence[Expr]) -> SatResult`: `Sat(witness)` when some completion of the
    `given` facts meets the input-only rules and proves an outcome, that is, for some outcome `o`,
    `ForAll(others, Implies(rest, o))` together with `Exists(others, rest)`. Task 3 uses it to shrink gap customers.
  - `validate.Undecided(witness: Model)`: severity `"warning"`; `_logical` adds at most one, from `undecided`.

`tests/policies/defects/gap.yaml`:

```yaml
policy: defect-gap
version: "1"
variables:
  late: { sort: Bool, role: system, description: The parcel arrived late. }
  refund: { sort: Bool, role: derived, description: The customer gets a refund. }
rules:
  - { id: G1, when: late, then: refund }
outcomes:
  refund: { refund: true }
```

- [ ] **Step 1: Write the failing tests:**
  - `test_validate.py::test_gap_is_a_warning`: `Undecided({"late": BoolLit(False)})` is in `report("defects/gap.yaml")`,
    `severity(...) == "warning"`, and `gate` succeeds.
  - `test_validate.py::test_the_toy_policy_only_has_reviews` is unchanged and still passes (toy decides everyone).
  - `test_solver.py::test_blocked_rule_sets_are_not_found_again`: on `defects/not_total.yaml`,
    `totality(c, inputs)` is `Sat`, and `totality(c, inputs, blocked=[frozenset({"R4", "R8", "R10"})])` is `Unsat`.
  - `test_solver.py::test_decidable`: on `gap.yaml`, `decidable(c, inputs, given=[])` is `Sat` (late=true decides
    refund), and with `given=[late == false]` it is `Unsat`.
  - `test_solver.py::test_undecided_respects_blocked`: on `gap.yaml`, `undecided(c, inputs)` is
    `Sat({"late": False})` and with `blocked=[Cmp("eq", Var("late"), BoolLit(False))]` it is `Unsat`.
- [ ] **Step 2: Run** the five tests. Expected: FAIL (`Undecided` and `blocked` don't exist).
- [ ] **Step 3: Implement.** Then add the new expected `Undecided(...)` warnings to the exact tuples in
  `tests/unit/test_real_policies.py` for any reference policy that now reports one (`retail_refund.yaml` will: its
  only outcome is `refund`). Write the witness the solver returns into the test, after checking by hand that it
  really decides nothing.
- [ ] **Step 4: Run** the full checks (as Task 1, Step 4). Expected: all pass; `gate` results for the reference
  policies are unchanged.
- [ ] **Step 5: Commit** `core: undecided inputs (gaps) as a warning; blocked rule sets in totality`.

---

### Task 3: `core.problems`: every problem, each with its own customer

**Files:**
- Create: `src/policyproof/core/problems.py`
- Create: `tests/policies/defects/clashes.yaml`
- Test: `tests/unit/test_problems.py`, `tests/laws/test_problems_laws.py`

**Interfaces:**
- Consumes: Task 2's `totality(..., blocked=)` and `undecided(..., blocked=)` and `decidable`; `solver.check`, `solver.fact`,
  `semantics.rule_expr`, `decide.decide`.
- Produces:

```python
type Customer = tuple[tuple[str, Lit], ...]          # sorted by variable name

@dataclass(frozen=True, slots=True)
class Says:            # what one rule alone forces for this customer, on variables that appear in outcomes
    rule: str
    forces: tuple[tuple[str, Lit], ...]

@dataclass(frozen=True, slots=True)
class Clash:           # the rules can't all hold for this customer
    customer: Customer             # minimal: every completion of it clashes
    witness: Customer              # a complete input assignment that extends `customer`
    rules: tuple[str, ...]         # a minimal set of rules that can't all hold, in policy order
    says: tuple[Says, ...]         # one per rule in `rules`

@dataclass(frozen=True, slots=True)
class Gap:             # the rules hold but prove no outcome
    customer: Customer             # minimal: every completion of it is undecided
    witness: Customer
    rules: tuple[str, ...]         # the rules that mention any variable of `customer`, in policy order

@dataclass(frozen=True, slots=True)
class OutrightConflict:            # the rules contradict with no facts at all
    rules: tuple[str, ...]

@dataclass(frozen=True, slots=True)
class GaveUp:
    check: str
    reason: str

type Found = OutrightConflict | Clash | Gap | GaveUp

@dataclass(frozen=True, slots=True)
class Problems:
    found: tuple[Found, ...]       # outright conflict alone if any; else clashes, then gaps, then GaveUp
    complete: bool                 # False when the cap was hit or the solver gave up

DEFAULT_CAP = 25

def problems(c: Compiled, *, cap: int = DEFAULT_CAP) -> Problems: ...
def still_a_problem(c: Compiled, f: Clash | Gap) -> bool: ...
    # Clash: the rules are unsat with `f.witness`; Gap: `decide` on `f.witness` (as system facts) isn't Decided
def groups(found: Sequence[Found]) -> tuple[tuple[int, ...], ...]: ...
    # indices of problems connected through shared rules, each group in order, groups ordered by first index
```

`tests/policies/defects/clashes.yaml` (the prototype's courier and sale problems):

```yaml
policy: defect-clashes
version: "1"
sorts:
  Carrier: [POST, COURIER]
variables:
  carrier: { sort: Carrier, role: system, description: Who delivered the parcel. }
  daysLate: { sort: Int, role: system, description: Days after the promised date. }
  asked: { sort: Bool, role: ask, question: Would you like a refund?, description: The customer asked for a refund. }
  lost: { sort: Bool, role: system, description: The parcel was lost. }
  damaged: { sort: Bool, role: system, description: The item arrived damaged. }
  sale: { sort: Bool, role: system, description: The item was bought in the sale. }
  refund: { sort: Bool, role: derived, description: The customer gets a refund. }
  replace: { sort: Bool, role: derived, description: The item is replaced. }
rules:
  - { id: C4, when: { eq: [carrier, COURIER] }, then: { not: refund } }
  - { id: C5, when: { and: [{ eq: [carrier, COURIER] }, { gt: [daysLate, 0] }, asked] }, then: refund }
  - { id: C6, when: lost, then: refund }
  - { id: C7, when: damaged, then: replace }
  - { id: C8, when: sale, then: { not: replace } }
  - { id: C9, constraint: { ge: [daysLate, 0] } }
outcomes:
  refund: { refund: true }
  replace: { replace: true }
  nothing: { refund: false, replace: false }
```

Algorithm (the parts the signature doesn't fix):

```
problems(c):
  if check(c, []) is Unsat(core): return Problems((OutrightConflict(rule ids of core),), True)
  clashes: loop up to cap
      totality(c, inputs, blocked=rule sets found so far)
        Unsat -> done
        Unknown -> GaveUp, incomplete
        Sat(w):
          - rules R: deletion-minimise the core of check(c, facts(w)) over rule labels (check with rules=False and
            each rule's rule_expr tracked by RuleLabel)
          - customer: deletion-minimise facts(w): drop a fact while R stays unsat with the rest
          - says: per rule in R, per outcome variable of finite sort, the value v with
            check(c, [rule] + customer + [var != v], rules=False) Unsat
  gaps: loop up to cap
      undecided(c, inputs, blocked=exprs blocked so far)
        Sat(w):
          - customer: drop a fact f when decidable(c, inputs, given=customer minus f) is Unsat
            (no completion of the remaining facts is decided)
          - block: the conjunction of the customer's Bool/enum facts when there is one, else the whole customer
            (so integer-only gaps stop at the cap rather than loop on each integer)
```

- [ ] **Step 1: Write the failing tests** in `tests/unit/test_problems.py`:
  - `test_three_rules_clash_with_no_pair_at_fault`: on `defects/not_total.yaml`, exactly one `Clash` with
    `rules == ("R4", "R8", "R10")`, `customer == (("coolingOff", True), ("outsideControl", True))` (as `BoolLit`s),
    and `says` forcing `credit = true` for R4, `refund = true` for R8, nothing for R10.
  - `test_clashes_are_distinct_by_rule_set`: on `clashes.yaml`, the clashes' rule sets are exactly
    `{("C4", "C5"), ("C4", "C6"), ("C7", "C8")}`. The `("C4", "C6")` customer is
    `(("carrier", COURIER), ("lost", True))`.
  - `test_an_integer_input_gives_one_clash_per_rule_set`: on `clashes.yaml`, `("C4", "C5")` appears once; its
    customer has `carrier`, `asked` and a positive `daysLate`; `complete` is True.
  - `test_a_gap_has_a_minimal_customer`: on `gap.yaml`, `found == (Gap((("late", False),), (("late", False),),
    ("G1",)),)`.
  - `test_an_outright_conflict_stops_there`: on `defects/conflict.yaml`,
    `found == (OutrightConflict(("K1", "K2")),)`.
  - `test_the_toy_policy_has_no_problems`: `problems(compile(toy)) == Problems((), True)`.
  - `test_solver_giving_up_is_reported`: monkeypatch `policyproof.core.problems.totality` to return
    `Unknown("timeout")`. Expect a `GaveUp("clashes", "timeout")` in `found` and `complete is False`.
  - `test_groups_follow_shared_rules`: for the three clashes of `clashes.yaml`, the two that contain C4 form one
    group and the C7/C8 clash forms another.
  - `test_still_a_problem`: true for each found problem on the policy it came from.
- [ ] **Step 2: Write the laws** in `tests/laws/test_problems_laws.py`, using `strategies` policies (keep examples
  small: `max_examples=50`):
  - **P1:** every `Clash` customer really clashes (`check` Unsat with its facts), and dropping any one fact of it
    makes it consistent with at least one completion.
  - **P2:** every `Clash.witness` extends its `customer`.
  - **P3:** `problems(c).found == ()` and `complete` exactly when `validate` reports no `NotTotal`, `Undecided` or
    `Conflict`.
- [ ] **Step 3: Run** `uv run pytest tests/unit/test_problems.py tests/laws/test_problems_laws.py -q`.
  Expected: FAIL (module missing).
- [ ] **Step 4: Implement** `core/problems.py`.
- [ ] **Step 5: Run** the full checks. Expected: all pass; the core contract still holds.
- [ ] **Step 6: Commit** `core: enumerate problems with minimal example customers`.

---

### Task 4: `authoring.document`: sentences, anchors and edits

**Files:**
- Create: `src/policyproof/authoring/__init__.py` (docstring only), `src/policyproof/authoring/document.py`
- Modify: `pyproject.toml` (new contract: `authoring.document`, `authoring.plain`, `authoring.examples` and
  `authoring.merge` may import only the core and guards, no `policyproof.effects`, pydantic or SDK)
- Test: `tests/unit/test_document.py`, `tests/laws/test_document_laws.py`

**Interfaces:**
- Produces:

```python
@dataclass(frozen=True, slots=True)
class Anchor:
    section: str        # the nearest heading's text above the sentence; "" before the first heading
    text: str           # the sentence, whitespace collapsed, list markers ("-", "*", "1.") removed
    n: int = 0          # 0 for the first occurrence of this text in this section, then 1, 2, ...

@dataclass(frozen=True, slots=True)
class Sentence:
    anchor: Anchor
    start: int          # offsets into Document.text of the sentence's own characters
    end: int

@dataclass(frozen=True, slots=True)
class Document:
    text: str
    sentences: tuple[Sentence, ...]

@dataclass(frozen=True, slots=True)
class Replace:
    at: Anchor
    text: str

@dataclass(frozen=True, slots=True)
class Insert:
    section: str
    after: Anchor | None   # None: a new paragraph at the end of the section
    text: str

@dataclass(frozen=True, slots=True)
class Remove:
    at: Anchor

type Edit = Replace | Insert | Remove

def parse(text: str) -> Document: ...
def locate(doc: Document, a: Anchor) -> Sentence | None: ...
    # exact (section, text, n); else the most similar text in the same section with SequenceMatcher ratio >= 0.8
def apply(doc: Document, edits: Sequence[Edit]) -> Result[Document, str]: ...
    # edits apply in order against the evolving document; an anchor that can't be located is Failure(message)
def touched(before: Document, after: Document, edits: Sequence[Edit]) -> tuple[Anchor, ...]: ...
    # the anchors in `after` of every replaced or inserted sentence, for partial re-extraction
```

Sentence rules: headings (`#`…) set the section and are not sentences; fenced code is skipped; each paragraph or
list item is split at `(?<=[.!?])\s+(?=[A-Z0-9"“(])`.

- [ ] **Step 1: Write the failing tests:**
  - `test_parse_finds_sections_and_sentences`: on the prototype's policy markdown, the anchors read
    `("Couriers", "Courier parcels are never refunded.", 0)` etc., and `doc.text[s.start:s.end]` is the sentence text
    with its original whitespace.
  - `test_duplicate_sentences_get_distinct_anchors`: "Keep your receipt." in two sections gets `n=0` in each; twice
    in one section gets `n=0` and `n=1`. A `Replace` of the second changes only the second.
  - `test_insert_and_remove`: `Insert(after=...)` adds the sentence after the anchor in the same paragraph;
    `Insert(after=None)` appends a paragraph at the end of the section; `Remove` deletes the sentence and one
    adjacent space.
  - `test_locate_survives_small_edits`: after the author changes "never" to "not" in a sentence outside the
    studio, `locate` with the old anchor finds it; with an unrelated text it returns None.
  - `test_a_missing_anchor_is_a_failure`: `apply(doc, [Replace(Anchor("Nope", "x."), "y.")])` is a `Failure`
    that names the sentence.
- [ ] **Step 2: Write the laws:**
  - **D1:** `parse(doc.text) == doc`.
  - **D2:** after `Replace(a, t)`, `parse` of the result has `Anchor(a.section, t)`, and every other anchor is
    unchanged.
  - **D3:** applying `[]` is the identity.
- [ ] **Step 3: Run.** Expected: FAIL. **Step 4: Implement.** **Step 5: Run** the full checks. Expected: pass.
- [ ] **Step 6: Commit** `authoring: markdown sentences, anchors and edits`.

---

### Task 5: `authoring.plain` and `authoring.examples`

**Files:**
- Create: `src/policyproof/authoring/plain.py`, `src/policyproof/authoring/examples.py`
- Test: `tests/unit/test_plain.py`, `tests/unit/test_examples.py`

**Interfaces:**
- Consumes: Task 1's `Display`; Task 3's `Customer`; `guards.values.literal_for`; `decide.decide`.
- Produces:

```python
# plain.py
def phrase(v: Variable, value: Lit) -> str: ...
    # display phrase or template; else f"{v.description.rstrip('.')}: {render.pretty(value)}"
def customer_phrases(p: CheckedPolicy, customer: Customer) -> tuple[str, ...]: ...
def outcome_label(o: Outcome) -> str: ...
    # o.display; else the name split on camelCase and underscores, first letter capitalised

# examples.py
@dataclass(frozen=True, slots=True)
class Example:
    id: str
    customer: Customer     # complete enough to decide
    outcome: str

def to_facts(p: CheckedPolicy, ex: Example) -> Facts: ...
    # system -> FromSystem("example"); ask -> Answered(question, "example")
def holds(c: Compiled, ex: Example) -> bool: ...     # decide(...) is Decided with ex.outcome
def broken(c: Compiled, examples: Sequence[Example]) -> tuple[Example, ...]: ...
def loads(p: CheckedPolicy, text: str) -> Result[tuple[Example, ...], str]: ...
def dumps(examples: Sequence[Example]) -> str: ...
```

Examples file:

```yaml
examples:
  - id: late-courier-asked
    customer: { carrier: COURIER, daysLate: 3, asked: true }
    outcome: refund
```

- [ ] **Step 1: Write the failing tests:**
  - `test_phrases`: with Task 1's display, `phrase(carrier, COURIER) == "Came by courier"`,
    `phrase(daysLate, IntLit(3)) == "3 days late"`; without display, `"Who delivered the parcel: COURIER"`.
  - `test_outcome_label`: `"A refund"` from display; `"No refund"` from the name `noRefund`.
  - `test_examples_round_trip_and_hold`: on the toy policy, an example
    `{daysLate: 3, carrier: POST, wantsRefund: true} -> refund` loads, dumps back to the same text, `holds`, and with
    outcome `voucher` is in `broken`.
  - `test_bad_examples_name_the_problem`: an unknown variable, a derived variable, a wrong-sorted value, a duplicate
    id and an unknown outcome are each a `Failure` whose message has the example's id and the field.
- [ ] **Step 2: Run.** Expected: FAIL. **Step 3: Implement.** **Step 4: Run** the full checks. Expected: pass.
- [ ] **Step 5: Commit** `authoring: plain phrases and approved examples`.

---

### Task 6: `authoring.ports` and `authoring.merge`

**Files:**
- Create: `src/policyproof/authoring/ports.py`, `src/policyproof/authoring/merge.py`
- Create: `tests/authoring_fakes.py` (fake `Extractor`, `Drafter` and `Phraser`, scripted like `tests/fakes.py`)
- Modify: `pyproject.toml`: new contract: `authoring.ports` and `authoring.propose` import no `authoring.llm`,
  `effects.llm`, `effects.jev`, pydantic, pydantic-ai or SDK.
- Test: `tests/unit/test_merge.py`

**Interfaces:**
- Produces in `ports.py`:

```python
@dataclass(frozen=True, slots=True)
class Link:
    rule: str
    anchor: Anchor

@dataclass(frozen=True, slots=True)
class Extraction:
    policy: CheckedPolicy
    links: tuple[Link, ...]          # every rule has at least one link, unless added by hand in the YAML
    uncovered: tuple[Anchor, ...]    # sentences no rule came from

@dataclass(frozen=True, slots=True)
class Choose:
    outcome: str                     # an existing outcome's name

@dataclass(frozen=True, slots=True)
class Describe:
    text: str                        # a new outcome, or "it depends on ..." in the author's words

type Answer = Choose | Describe

@dataclass(frozen=True, slots=True)
class Situation:                     # what a drafter is told about the problem
    customer: tuple[str, ...]        # plain phrases (plain.customer_phrases)
    sentences: tuple[Anchor, ...]    # the sentences of the rules involved
    outcomes: tuple[tuple[str, str], ...]   # (name, label) of every outcome

class Extractor(Protocol):
    async def extract(self, doc: Document, *, vocabulary: CheckedPolicy | None = None,
                      only: tuple[Anchor, ...] | None = None, guidance: str = "") -> Result[Extraction, LLMError]: ...

class Drafter(Protocol):
    async def draft(self, doc: Document, situation: Situation, answer: Answer,
                    failure: str | None) -> Result[tuple[Edit, ...], LLMError]: ...

class Phraser(Protocol):
    async def title(self, p: CheckedPolicy, customer: tuple[str, ...]) -> Result[str, LLMError]: ...
    async def sentence(self, p: CheckedPolicy, rule: Rule) -> Result[str, LLMError]: ...
```

- Produces in `merge.py`:

```python
@dataclass(frozen=True, slots=True)
class Additions:
    variables: tuple[Variable, ...]
    values: tuple[tuple[str, str], ...]      # (sort, new value) on existing sorts
    outcomes: tuple[Outcome, ...]

@dataclass(frozen=True, slots=True)
class RuleChange:
    anchor: Anchor
    before: tuple[Rule, ...]
    after: tuple[Rule, ...]

def merge(base: Extraction, part: Extraction, replaced: Sequence[Anchor]) -> Result[Extraction, tuple[SortError, ...]]: ...
    # drop base rules linked only to `replaced` anchors; add part's rules with fresh ids (R<n>, n past the
    # highest number in use) and links; take sorts, variables and outcomes from `part` where it extends `base`
    # (part's vocabulary must contain base's: a missing name is a sort error); recompute `uncovered`; typecheck
def additions(before: CheckedPolicy, after: CheckedPolicy) -> Additions: ...
def rename(ex: Extraction, old: str, new: str) -> Result[Extraction, tuple[SortError, ...]]: ...
    # merge two names for one thing: substitute Var(old) -> Var(new) everywhere, drop `old`
def rule_changes(old: Extraction, new: Extraction) -> tuple[RuleChange, ...]: ...
    # per anchor, the rules differ (compared by rule_expr, ignoring ids); anchors on one side only count
```

- [ ] **Step 1: Write the failing tests** in `tests/unit/test_merge.py` (build extractions from `clashes.yaml` with
  hand-written links):
  - `test_merge_replaces_the_rules_of_a_changed_sentence`: replacing C4's sentence with a part holding one new rule
    drops C4, adds `R10`, and keeps every other rule and link.
  - `test_merge_adds_new_names_and_reports_them`: a part adding variable `insured` and outcome `voucher` merges, and
    `additions` lists exactly those.
  - `test_merge_rejects_an_ill_typed_part`: a part whose rule uses `refnd` is
    `Failure((UnknownName(...),))`.
  - `test_rename_merges_two_names`: renaming `asked` to `wantsRefund` (added as a duplicate first) leaves one
    variable and rewrites C5.
  - `test_rule_changes`: a re-extraction that changes C5's condition and drops C8's sentence lists exactly those
    two anchors.
- [ ] **Step 2: Run.** Expected: FAIL. **Step 3: Implement** `ports.py`, `merge.py` and `tests/authoring_fakes.py`.
- [ ] **Step 4: Run** the full checks. Expected: pass; the new contracts hold.
- [ ] **Step 5: Commit** `authoring: ports, merging partial extractions, rule changes`.

---

### Task 7: `authoring.propose`: an answer to a checked change

**Files:**
- Create: `src/policyproof/authoring/propose.py`
- Test: `tests/unit/test_propose.py`, `tests/laws/test_propose_laws.py`

**Interfaces:**
- Consumes: Tasks 3–6.
- Produces:

```python
@dataclass(frozen=True, slots=True)
class Draft:                          # the author's current state
    doc: Document
    extraction: Extraction
    examples: tuple[Example, ...]

@dataclass(frozen=True, slots=True)
class Proposal:
    edits: tuple[Edit, ...]
    after: Draft                      # examples unchanged; propose never approves examples itself
    fixes: tuple[int, ...]            # indices into `before.found` that are no longer problems
    still_open: tuple[int, ...]       # targeted indices that still are
    new: tuple[Found, ...]            # problems after that were not problems before (by still_a_problem)
    broken: tuple[Example, ...]
    additions: Additions
    answered: bool | None             # Choose: every target witness now decides that outcome; Describe: None
    attempts: int

@dataclass(frozen=True, slots=True)
class EditFailed:
    message: str

@dataclass(frozen=True, slots=True)
class Unextractable:
    message: str

type ProposeError = LLMError | EditFailed | Unextractable

async def propose(state: Draft, before: Problems, target: tuple[int, ...], answer: Answer, *,
                  drafter: Drafter, extractor: Extractor, retries: int = 2) -> Result[Proposal, ProposeError]: ...
async def reword(state: Draft, before: Problems, target: tuple[int, ...], edits: tuple[Edit, ...], *,
                 extractor: Extractor) -> Result[Proposal, ProposeError]: ...
def approve(state: Draft, p: Proposal, before: Problems, answers: Mapping[int, str]) -> Draft: ...
    # p.after plus one Example per fixed target, from its witness and its answer; ids from the customer phrases
```

Loop: draft → `apply` (a `Failure` is a failed attempt with that reason) → `extract(only=touched, vocabulary=current
policy)` → `merge` (a sort error is a failed attempt) → compile, `problems`, the checks. An attempt is good when every
target is fixed, `answered` isn't False, `new` and `broken` are empty. Retry with a `failure` text that names what
went wrong. After the last attempt, return the attempt with the fewest of (still open + new + broken), as a
`Success`. Only when every attempt failed before checking, return the last `EditFailed` or `Unextractable`. An
`LLMError` returns at once.

- [ ] **Step 1: Write the failing tests** with the fakes and `clashes.yaml` (extractions hand-built):
  - `test_a_good_answer_fixes_the_clash`: target the C4/C5 clash with `Choose("refund")`. The drafter's
    `Replace(C4's anchor, "Courier parcels are never refunded, unless they arrive late and the customer asks.")` and
    the extractor's matching rule give `fixes == (that index,)`, `new == ()`, `answered is True` and `attempts == 1`.
  - `test_a_change_that_breaks_an_example_is_retried`: the first draft breaks an approved example and the second
    doesn't. Expect `attempts == 2`, and the drafter's second call received a `failure` that names the example's
    id.
  - `test_the_best_attempt_is_returned_when_none_is_clean`: both attempts leave a new problem. The result is a
    `Success` with that problem in `new` and `attempts == 3` (one plus two retries).
  - `test_a_misquoted_sentence_is_retried_then_reported`: the drafter always edits a sentence that doesn't exist.
    The result is `Failure(EditFailed(...))` naming it, after `retries + 1` calls.
  - `test_an_unmergeable_extraction_is_retried`: the first extraction uses an unknown name and the second is fine.
    Expect `attempts == 2`.
  - `test_reword_skips_the_drafter`: the author's own edits are checked the same way, with `attempts == 1`.
  - `test_approve_saves_examples`: approving the first test's proposal with `{index: "refund"}` adds one example
    that `holds` on the new policy.
  - `test_llm_errors_stop_at_once`: a drafter returning `Unavailable` gives `Failure(Unavailable(...))` after one
    call.
- [ ] **Step 2: Write the law:**
  - **PR1:** for any proposal the fakes produce, `p.fixes`, `p.still_open` and `p.new` agree with `still_a_problem`
    on `p.after`'s compiled policy.
- [ ] **Step 3: Run.** Expected: FAIL. **Step 4: Implement.** **Step 5: Run** the full checks. Expected: pass.
- [ ] **Step 6: Commit** `authoring: proposals checked by Z3 and approved examples`.

---

### Task 8: `authoring.llm.extractor`: the pydantic-ai extractor

**Files:**
- Create: `src/policyproof/authoring/llm/__init__.py`, `src/policyproof/authoring/llm/extractor.py`,
  `src/policyproof/authoring/llm/prompts.py`
- Modify: `pyproject.toml`: `extract = ["pydantic-ai-slim>=2.54"]`
- Test: `tests/unit/test_llm_extractor.py`, `tests/unit/test_authoring_prompts.py`

**Interfaces:**
- Consumes: `effects.llm.exprmodel` (the recursive expression model), the `_run` pattern in
  `effects.llm.readers` (copy its exception mapping: no import from `effects.llm.readers`' private names), the codec
  and typecheck, Task 4's `Document`, Task 6's `Extraction` and `Extractor`.
- Produces: `LLMExtractor(model: Model, retries: int = 2)`, an `Extractor`. The structured output is
  `ExtractionOut`: sorts; variables (name, sort, role, `question` for `ask`, description, display); rules (each with
  `sentence: int`, the 1-based number of the sentence in the prompt, and one of `when`/`then`, `define`/`as`,
  `constraint`, as `exprmodel` expressions); outcomes (name, assignment, display).

Prompt (in `prompts.py`, a pure function of its inputs, snapshot-tested):
- the whole document's sentences, numbered, grouped under their headings;
- with `vocabulary`: its sorts, variables and outcomes, with "use these names; add a name only when a sentence needs
  one";
- with `only`: "extract rules only from sentences N, M";
- `guidance` verbatim;
- the format's rule kinds, and "a sentence that doesn't decide what a customer gets is background: extract nothing
  from it".

Output validator: build the policy data and `codec.decode` it. With `vocabulary`, the vocabulary's names must all be
present. On a `DecodeError` or `IllTyped`, raise `ModelRetry` with the paths and messages. A rule's `sentence` must be
a listed number (in `only` when given). `uncovered` is every listed sentence (in `only` when given) that no rule
cites.

- [ ] **Step 1: Write the failing tests** with pydantic-ai's `FunctionModel` (no network):
  - `test_extracts_and_links`: a scripted `ExtractionOut` for the prototype's courier section gives a policy that
    typechecks, links each rule to its sentence's anchor, and lists the background sentence in `uncovered`.
  - `test_ill_typed_output_is_sent_back`: the first output uses an unknown name. The second call's messages contain
    the decode error's path, and the result is a `Success`.
  - `test_vocabulary_names_must_survive`: an output that drops a vocabulary variable is sent back.
  - `test_retries_run_out_as_malformed`: three ill-typed outputs give `Failure(Malformed(...))`.
  - `test_authoring_prompts.py::test_extraction_prompt_snapshot`: the prompt for the prototype's document, with and
    without `vocabulary`/`only`, matches the stored snapshots (follow the M2 prompt snapshot tests).
- [ ] **Step 2: Run.** Expected: FAIL. **Step 3: Implement.** **Step 4: Run** the full checks. Expected: pass; only
  `authoring.llm` imports pydantic-ai.
- [ ] **Step 5: Commit** `authoring: a pydantic-ai extractor, whole document, sentence links`.

---

### Task 9: `authoring.llm.drafter` and `authoring.llm.phraser`

**Files:**
- Create: `src/policyproof/authoring/llm/drafter.py`, `src/policyproof/authoring/llm/phraser.py`
- Modify: `src/policyproof/authoring/llm/prompts.py`
- Test: `tests/unit/test_llm_drafter.py`, `tests/unit/test_llm_phraser.py`, prompt snapshots

**Interfaces:**
- Produces:
  - `LLMDrafter(model: Model, retries: int = 1)`, a `Drafter`. Its output is a list of edits, each with `kind`
    (`replace`, `insert` or `remove`), the exact current sentence text, the section, and the new text. These map to
    `document.Edit`, with the anchor's `n` found by matching the quoted text in order.
  - `LLMPhraser(model: Model)`, a `Phraser`. `title` is one sentence of at most 20 words. `sentence` writes a rule
    as one plain sentence using the variables' descriptions and displays.
- Drafter prompt: the document, the situation's plain phrases, the involved sentences, the outcome labels, the
  answer, and the previous `failure` when given. It asks for the smallest change, in the document's own style, and
  says never to change sentences that aren't involved unless a new sentence is needed.

- [ ] **Step 1: Write the failing tests** with `FunctionModel`:
  - `test_drafts_map_to_edits`: a scripted reply becomes `(Replace(anchor, text),)` with the right `n` for a
    duplicate sentence.
  - `test_failure_reaches_the_prompt`: the `failure` text appears in the model's messages.
  - `test_title_and_sentence`: each returns the scripted text; an empty reply is `Malformed`.
  - Prompt snapshots for drafting and phrasing.
- [ ] **Step 2: Run.** Expected: FAIL. **Step 3: Implement.** **Step 4: Run** the full checks. Expected: pass.
- [ ] **Step 5: Commit** `authoring: LLM drafter and phraser`.

---

### Task 10: Reference documents, the extractor benchmark, live tests, README

**Files:**
- Create: `examples/authoring/refund_policy.md` (copied from `~/code/policy-reasoning-lab/policy/refund_policy.md`),
  `examples/authoring/toy.md`, `examples/authoring/retail_refund.md`, `examples/authoring/flight_disruption.md`
- Create: `examples/authoring/names/<policy>.yaml` (extracted name → reference name, per policy)
- Create: `src/policyproof/authoring/bench.py`: `async def bench(doc_path, reference: CheckedPolicy | None, cases:
  CaseFile | None, names: Mapping[str, str], extractor: Extractor) -> BenchResult`, plus
  `python -m policyproof.authoring.bench --model <pydantic-ai model string> [docs...]`
- Modify: `tests/live/test_live.py`: one extraction and one proposal on the toy document, `needs_bedrock`
- Modify: `README.md`: an "Authoring" section (extraction, problems, proposals; the studio comes in M5)
- Test: `tests/unit/test_bench.py`

**Interfaces:**
- `BenchResult(clashes: int, uncovered: tuple[Anchor, ...], decisions_matched: int, decisions_total: int,
  mismatches: tuple[str, ...])`. These are the spec's three criteria (Calls 6): no clashes, every sentence a rule
  or background, and every M3 turn case's facts decide the same outcome under the name map.

- [ ] **Step 1: Write the three markdown documents** from each reference YAML's rules, `explain` texts and
  sources. Each states every rule in plain sentences, under headings, plus at least one background sentence. Commit
  them on their own: `examples: markdown sources for the reference policies`.
- [ ] **Step 2: Write the failing test** `test_bench_scores_a_perfect_extraction`: with a fake extractor that
  returns the reference policy itself (identity name map), `decisions_matched == decisions_total` and `clashes ==
  0`. A fake returning a policy with one rule flipped gives the mismatching case ids.
- [ ] **Step 3: Run.** Expected: FAIL. **Step 4: Implement** `bench.py`. **Step 5: Run** the full checks.
  Expected: pass.
- [ ] **Step 6: Commit** `authoring: extractor benchmark against the reference policies`.
- [ ] **Step 7: Ask the user before the paid run.** One extraction per document (4 calls plus any retries, at most 12)
  on the model they choose. Then run the benchmark and write the results into the README section.
  - **If every criterion is met,** pydantic-ai is the extractor (spec, Calls 6).
  - **If not,** report the failures to the user. Adding a LangExtract `Extractor` behind the same port becomes a
    follow-up task with its own paid run.
- [ ] **Step 8: Run the live tests, only with the user's go-ahead.** Run
  `uv run pytest -m live tests/live/test_live.py -k authoring`. Expected: pass. Commit
  `authoring: live tests and README`.
