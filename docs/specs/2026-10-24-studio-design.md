# policyproof studio: authoring a policy without knowing logic

*2026-10-24. Design spec for review. Builds on milestone 1 (`docs/specs/2026-10-03-core-design.md`), milestone 2
(`docs/specs/2026-10-03-effects-design.md`), milestone 3 (`docs/specs/2026-10-08-eval-design.md`) and the
policy-reasoning-lab's extraction spike (`~/code/policy-reasoning-lab`: `BRIEF.md`, `lab/lx_extract.py`,
`review/policy_review.html`). The clickable prototype agreed in brainstorming is
`docs/specs/assets/2026-10-24-studio-prototype.html`: open it in a browser. Its problems and proposals are scripted,
but its layout, wording and flow are the agreed design.*

## Purpose

policyproof can prove decisions from a policy, but someone has to write the policy first, and today that means
writing YAML expression trees. The people who own business policies are in operations, customer service or legal.
They know the rules of the business well, but they have never read a logic formula.

`policyproof studio` is a local tool for them. They give it a markdown policy document. It extracts the rules, finds
every problem Z3 can find (rules that contradict each other, customers no rule decides, sentences that didn't become
rules, two names for one thing), and walks the author through fixing each one in plain English. Every problem is
shown as an **example customer**. The author answers a business question about that customer ("what should this
customer get?"). The tool proposes a wording change to the document and its rules, Z3 checks the change, and the
author accepts it. At the end the author has a markdown document and a policyproof policy that say the same thing,
pass `validate`, and come with a set of approved example customers.

## Goals

- An author with no logic background can take a markdown policy to a saved policy with **no errors left and every
  warning answered**, without ever needing to read a formula.
- Every problem the validator can find is presented the same way: an example customer or situation in plain English,
  one business question, a proposed change, a check, accept.
- The document and the rules never drift apart. A fix changes the sentence in the document and the rules extracted
  from it together.
- Nothing reaches the saved policy unchecked. Every proposal is checked by Z3 against the whole policy and against
  every example customer approved so far, before the author sees it.
- Hand fixes survive re-extraction: extracting again shows each rule that changed next to the author's version, and
  the author picks.

## Non-goals

- Hosting, accounts, several authors working together, permissions. It runs on the author's machine for one person.
- Editing formulas as the main way of working. "Show the logic" is read-only. An expert can still edit the YAML in an
  editor and open it in the studio again.
- Bedrock Automated Reasoning import or export.
- Running conversations against the policy. That is `policyproof eval`'s job (milestone 3).
- A phone layout beyond "it doesn't break". This is a desk tool.

## Anti-goals

These would make the studio a failure even if it worked:

- **Showing formulas, variable names or solver words by default.** `carrier = COURIER → ¬refund`, `wantsRefund`,
  "unsat" and "witness" never appear outside "Show the logic". Variable names appear only through their descriptions.
- **Applying a change Z3 hasn't checked,** or saying "every rule agrees" when the solver gave up. A `SolverGaveUp`
  is shown as a problem, never as a pass.
- **Silently losing an author's decision:** a hand fix overwritten by re-extraction, a dismissed warning that comes
  back without its reason, or an approved example customer whose answer changes without a warning.
- **Rules and document drifting apart,** so that the next extraction brings back a problem the author already fixed.

## Decisions

From the brainstorming with the user, as decided:

- **The author** is a business person who doesn't know logic. Everything is plain sentences and example customers.
- **The input** is a markdown policy document, opened from a file or pasted.
- **Local tool:** `policyproof studio` opens a page on the author's machine.
- **Both ways of fixing:** the author can change the rules directly (through the decision flow below) and can change
  the markdown and extract again.
- **Re-extraction shows a diff** of each changed rule against the author's hand fixes, and the author chooses which
  version to keep, rule by rule.
- **A problem is shown as an example customer** where the rules clash, in plain English.
- **The author decides what should happen to that customer; the tool proposes the wording change** and the author
  approves it. The author doesn't edit rules from scratch.
- **Several problems:** listed worst first; problems that share a rule are grouped into one decision, with "decide
  each one separately" as a way out; a problem involving three or more rules shows all of them, with no pair blamed;
  after each change everything is checked again, and anything new is marked as caused by the last change, with Undo.
- **All validator findings use the same style**, not only contradictions (mapping below).
- **The UI is TypeScript: React with an Elm-style loop.** One immutable state value, a pure
  `update(state, message)`, views as pure functions of the state, `useReducer` only.
- **The look of the prototype is approved:** the document as a sheet on the left, the decision on the right, a serif
  face for the policy text, semantic colours used only for problems (red), new problems (amber) and fixes (green),
  light and dark themes.

## The author's flow

The prototype shows all of this. In order:

1. **Start.** `policyproof studio delivery-refunds.md` (or no argument, then open or paste a document). The studio
   creates or opens the workspace next to the document (see Files) and extracts if there is no policy yet.
2. **Review.** The screen shows the document on the left and the next problem on the right. A summary bar counts open
   problems, fixed problems and approved example customers.
3. **Decide.** For each problem: the situation, what each rule involved says (with its sentence quoted from the
   document), one question with two to four answers, and "It depends on something else…" where it makes sense. That
   option asks what it depends on, in a sentence.
4. **Proposal.** After an answer, the tool shows the change it would make: the sentences changed in the document as
   a word diff, new sentences, removed ones. Underneath it lists what the check found: which problems the change
   fixes, which are still open, any new problem it would cause, and whether every approved example customer still
   gets the same answer.
5. **Accept, edit or choose differently.** "Edit the wording" lets the author rewrite a proposed sentence; it is
   extracted and checked again as they type (debounced). A proposal that causes a new problem can still be
   accepted, with the button changed to "Accept anyway".
6. **After accepting:** the document shows the change as a tracked change, the problem moves to "fixed", the
   customer is saved as an approved example with the chosen answer, and the next problem opens. A banner says what the
   last change fixed and broke, with Undo.
7. **Done.** When no errors are left and every warning is answered, the studio says so. Every accept has already
   been written to disk (Calls 3).

Clicking a sentence in the document opens the problem it is part of.

## Every kind of problem, in the same style

Order of work: errors first (contradictions and gaps, because the policy can't be trusted until they're fixed), then
uncovered sentences, then warnings, then items to review. Warnings and review items can be dismissed with a reason;
the reason is saved and the item doesn't come back unless the rules involved change.

| Validator finding | Shown as | The question | What accepting does |
|---|---|---|---|
| A contradiction for some customer (`NotTotal` where the rules can't all hold) | An example customer and what each rule involved says | "What should this customer get?" | Rewrites the sentences of the rules that give the wrong answer |
| An outright `Conflict` (rules that contradict with no facts at all) | The rules involved and what each one demands | "Which of these is true?" | Rewrites or removes sentences |
| A gap (`Undecided`, a new warning-level finding: see Calls 1) | "Nothing in the policy says what happens to …" | "What should this customer get?" | Adds a sentence to the document, in the right section, and its rule |
| A sentence nothing was extracted from (new, see Extraction) | The sentence highlighted in the document | "Should this decide what customers get, or is it background information?" | Background: marked so it isn't flagged again. Decides: extracted again with that guidance, and the new rule is shown |
| `NearDuplicate` | "These look like the same thing: *the customer wants a refund* and *the customer asked for a refund*" | "Are they the same?" | Yes: merges them. No: asks for one sentence on how they differ, which goes into both descriptions |
| `UnreachableOutcome` | "No customer can ever get a voucher" | "Is that intended?" | No: treated like a gap for a customer who should get it |
| `OverlappingOutcomes` | An example customer who gets both | "Should anyone get both?" | No: like a contradiction. Yes: dismissed with that reason |
| `ImpossibleInput` | "The rules say a parcel can never be delivered by courier" | "Is that intended?" | No: the rule that rules it out is shown as a contradiction to fix |
| `InputsRelated` | The rule, and a customer whose answers break it | "Can this really never happen?" | Yes: dismissed with the reason. No: rewritten |
| `UnusedVariable`, `DisjointGroups` | The thing nothing uses, or the two groups of rules that share nothing | "Is this part of the policy?" | Removes it, or merges names |
| `DefinitionToReview`, `ConstraintRule` | The rule as a sentence: "*Late* means 2 or more days late, and only that" | "Is that exactly right?" | Yes: dismissed. No: rewritten |
| `SolverGaveUp` | "This part of the policy is too complex to check" | none | Not dismissable; points at the rules involved |

This mapping is a starting point; the wording is the author-facing part and should be tested on real documents.

## Calls made after the design review

A reviewer read this spec as its builder and asked six questions. These are the answers. They are the spec
author's calls, not the user's, and are marked so they can be checked.

1. **What a gap is.** *(Call.)* A gap is a complete set of input values (every `system` and `ask` variable given)
   for which the rules hold but prove no outcome, so `decide` with every fact known would still `Escalate`.
   - It is judged on complete inputs, then shrunk to a minimal example customer for display. The shrinking keeps
     only facts whose removal would let some outcome be proven.
   - It joins the core validator as a new finding (`Undecided`) with severity **warning**, so `gate` and every
     existing M1–M3 user see no change.
   - The studio treats it as something that must be answered before Done. The answers are "this customer should
     get …", which adds or changes rules, or "a person should decide this one", which is a dismissal with a reason.
   - A policy like `retail_refund.yaml`, whose only outcome is `refund`, will show its non-refund customers as gaps.
     The natural answer, "nothing", adds an outcome for it. That is the intended behaviour.
2. **What an answer is.** *(Call.)* An answer is an **outcome**: it says what this customer should get.
   - **Options:** the outcomes the clashing rules point to, plus every other existing outcome under "Something
     else…", where the author can also describe a new outcome in a sentence. "Both" is offered only when an outcome
     for both exists or is being added.
   - **Wording:** the question and option labels may be written by the LLM in plain words. The value behind each
     option is always an outcome name, or a new outcome the proposal adds.
   - **Approved example:** its facts are complete enough that `decide` returns `Decided(that outcome)`. The facts
     must prove the answer, not merely be consistent with it.
   - **New names:** a fix may add variables, enum values and outcomes. Re-extraction keeps the existing names fixed
     and may add new ones only when a fix needs them.
     - Each addition is shown to the author in plain words before they accept, for example "The agent will now ask
       customers: *Was the parcel insured?*"
     - A new input is classed `ask` or `system`, and the proposal shows that choice as "the agent asks the customer"
       or "it comes from your systems". The author can switch it.
3. **When files change.** *(Call.)* On every accept. The document, the policy and the examples file are written
   straight away, and there is no Save button: the Done state says "Everything is saved".
   - **Undo** history lives in the workspace folder, and undoing rewrites the files.
   - **File watching:** the watcher ignores the studio's own writes (by content hash). Only outside edits offer
     "Extract again".
   - **Unfinished work:** a policy with open errors is saved, because it is work in progress. Runtime use is already
     protected by `gate`.
   - **Quitting halfway:** the next start reopens the same state.
4. **Where the links from rules to the document live.** *(Call.)* In the workspace, not in the policy format.
   - The policy format and codec do not change, apart from the display-phrase field. `source` keeps its short
     label.
   - Each link anchors a rule to the **text of its sentence plus the heading of its section**, and is re-found after
     outside edits by exact match, then by closest match within the section.
   - Character offsets are recomputed on load and never stored.
   - On "Extract again", old and new rules are matched through these anchors. A rule whose sentence can't be
     re-found counts as changed.
5. **Rules with no sentence.** *(Call.)*
   - A rule with no sentence (for example one added by hand in the YAML) is shown with a plain sentence the LLM
     writes from it. It is clearly marked "not in your document" and raised as a review item: "Add this to the
     document?" Accepting adds the sentence where the proposal suggests.
   - The studio never writes YAML edits back into the document on its own.
   - Opening a policy that has no markdown document at all is out of scope for the first version.
6. **Choosing the extractor.** *(Call.)*
   - **The test set:** the lab's `refund_policy.md`, plus markdown versions of the three reference policies, written
     as part of the work from their YAML, the `explain` texts and the examples, and committed under `examples/`.
   - **Success,** per document:
     - after extraction, no contradictions;
     - every sentence either became a rule or is plainly background;
     - for every M3 turn case's facts, the extracted policy decides the same outcome as the hand-written one. A
       per-policy name map from extracted names to reference names is written once, by hand, for this.
   - Both extractors run on the same model. These runs call paid models, so they need the user's go-ahead first,
     with the number of calls stated.

## What has to exist in Python first

The studio is a thin UI over a Python authoring layer that doesn't exist yet. Build that first; it can be tested
without any UI.

### 1. Extraction: document to policy, sentence by sentence

- Reads the **whole document in one pass.** The lab showed that chunking silently broke the policy (names drifted
  between chunks and final-sale items became refundable).
- Produces a policyproof policy plus **links from each rule to the sentence it came from** (stored in the workspace
  and anchored as Calls 4 describes), and the list of sentences nothing was extracted from.
- **Re-extracting part of a document** (one changed sentence, or a new one) keeps the existing variable names and
  sorts fixed and passes them in as the vocabulary, so names don't drift.
- The lab used LangExtract on the whole document. Whether to use LangExtract or a pydantic-ai structured-output
  extractor (the format's JSON Schema was designed to double as a structured-output schema) is left to the builder,
  measured on the lab's refund policy and the three reference policies.

### 2. Problems: every problem, each with its own example customer

`validate` today reports at most one `NotTotal`, with one witness, and an outright `Conflict` only when the rules
contradict with no facts. The studio needs every distinct problem:

- For a contradiction: a **minimal example customer** (only the facts that matter for it) and the set of rules that
  can't all hold for that customer (an unsat core under those facts). Two problems are distinct when their rule sets
  differ.
- For a gap: a minimal example customer for whom the rules hold but no outcome is decided.
- Enumerate by blocking each problem found and searching again, with a cap and a clear "there may be more" when the
  cap is hit.
- For each rule in a problem: **what that rule says for this customer**, expressed through outcomes and derived
  variables ("No refund", "A $10 voucher", "Not both"), so the UI can put the clash side by side.
- Grouping is computed from shared rules, as in the prototype.

This belongs in the core: it is pure Z3 work on a compiled policy.

### 3. Plain language

- **Facts** are shown through variable descriptions, deterministically: `carrier = COURIER` becomes "Came by courier".
  To make this good, extraction writes a short display phrase for each value of an enum or boolean input; this is a
  new optional field in the policy format (the builder names it; it sits next to M3's `phrasings`, which are about
  reading customers, not showing facts).
- **The situation title** ("A courier parcel arrives 3 days late and the customer asks for a refund") may come from
  an LLM, with the fact phrases as the fallback when no model is available.
- **Rules are shown as their sentences from the document,** never re-rendered from logic. A rule without its own
  sentence (one added by a fix) gets the sentence the fix added to the document.

### 4. Proposals: the author's answer to a checked change

Given a problem, the author's answer (or "it depends on …" text, or their own wording), the document and the policy:

1. An LLM proposes the **smallest change to the document's sentences** that makes the policy give that answer for
   that customer: edited sentences, new sentences (with where they go), removed sentences.
2. The changed and new sentences are re-extracted into rules with the vocabulary fixed.
3. Z3 checks the result: the whole policy is validated again, the problem's customer gets the chosen answer, and
   every approved example customer still gets their approved answer.
4. If the check finds a new problem, try again a small number of times with the failure in the prompt; if every
   attempt fails, show the best one with its new problem listed, rather than nothing.

The author's own wording (from "Edit the wording") goes through steps 2 and 3 only.

### 5. The studio server

A small local HTTP API over the four pieces above plus the workspace files. Binds to 127.0.0.1 only and requires a
per-run token in the URL, like the brainstorming server, because it can read and write files. LLM calls go through
pydantic-ai model strings, configured like M3's `readers.yaml` (the builder decides the file or flags), so any
provider works.

## Files

Everything the author does is saved in plain files next to the document, so it can be put in git and reviewed:

```
delivery-refunds.md                   the document; the studio edits it when a fix is accepted
delivery-refunds.policy.yaml          the policy, in policyproof's format (unchanged apart from display phrases)
delivery-refunds.examples.yaml        approved example customers: facts and the expected outcome
.delivery-refunds.studio/             the workspace: extraction snapshot used for re-extraction diffs,
                                      links from rules to sentences (Calls 4), dismissed findings with their reasons,
                                      sentences marked background, undo history
```

The exact names, and whether the examples file reuses M3's case format (a turn case without a message would need a
new kind), are the builder's call. Approved examples must be usable by a later check outside the studio, so a change
made in an editor is caught too.

**Document changes while the studio is open:** if the markdown changes on disk (the author edited it in their own
editor), the studio notices and offers "Extract again", which leads to the rule-by-rule diff. Editing the markdown
freely inside the studio is not part of the first version.

## The UI

- **Stack:** React, TypeScript, Vite, the Elm-style loop described in Decisions. No other state library.
- **Types:** TypeScript types for the policy are generated from `src/policyproof/schema/policy.schema.json`. The
  API's own types (problems, proposals, workspace state) get a JSON Schema too, and their TypeScript is generated from
  it, so Python and TypeScript share one definition.
- **Every server response is parsed on arrival** with a small schema library (the builder picks it) into those
  types before the state sees it.
- **Tests:** Vitest for `update` and the views; property tests (fast-check) for `update`'s laws, for example Undo
  after any accepted change restores the previous state. The Python side keeps its own style and laws.
- **Shipping:** the built page is included in the Python package, so authors don't need Node. Node is only for
  developing the studio.
- **Look:** follow the prototype. It is responsive down to phone width and has light and dark themes.

## Package layout and boundaries

Suggested, for the builder to settle:

```
policyproof/core/problems.py        every problem with its example customer and rules       pure (core only)
policyproof/authoring/               extraction, plain language, proposals                  effects
policyproof/studio/                  the local server and the built page                    imports authoring
studio/                              the TypeScript source (repo root, not in the wheel)
```

Import contracts in the style of the earlier milestones: the core stays pure, and only `studio` imports the web
server. New extras: `[extract]` (already declared, empty) and `[studio]`.

## What's left to the builder

- LangExtract versus a pydantic-ai extractor, decided by measurement (see Extraction).
- The problem-enumeration algorithm and its cap.
- The web server library, the schema library on the TypeScript side, and file names.
- The name and shape of the display-phrase field in the policy format.
- How many retries a proposal gets, and the debounce on "Edit the wording".
- How the work splits into milestones. A natural split is the Python authoring layer (extraction, problems, plain
  language, proposals) as one milestone, testable with fakes and the reference policies, then the server and UI as
  the next.
