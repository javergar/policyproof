"""An author's answer to a checked change: the drafter writes the edit, the changed sentences are extracted again with
the current names, the result is merged, and Z3 checks it against the whole policy and every approved example before
the author sees it. A change that fixes the problem without breaking anything wins; otherwise the drafter is told what
went wrong and tries again, and after the last try the best attempt is shown with what it breaks.
"""
from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import assert_never

from returns.result import Failure, Result, Success

from policyproof.authoring.document import Anchor, Document, Edit, apply, gone, touched
from policyproof.authoring.examples import Example, broken, holds
from policyproof.authoring.extraction import Extraction
from policyproof.authoring.merge import Additions, Changed, additions, merge
from policyproof.authoring.plain import customer_phrases, outcome_label
from policyproof.authoring.ports import Answer, Choose, Describe, Drafter, Extractor, Situation
from policyproof.core._result import unreachable
from policyproof.core.problems import (
    Clash,
    Customer,
    Found,
    Gap,
    GaveUp,
    OutrightConflict,
    Problems,
    decides,
    problems,
)
from policyproof.core.problems import still_a_problem as _still
from policyproof.core.solver import Compiled, Sat, check, compile, decidable
from policyproof.core.syntax import CheckedPolicy, Cmp, Derived, Var
from policyproof.core.typecheck import SortError
from policyproof.effects.errors import LLMError


@dataclass(frozen=True, slots=True)
class Draft:
    """The author's current state."""

    doc: Document
    extraction: Extraction
    examples: tuple[Example, ...]


@dataclass(frozen=True, slots=True)
class Proposal:
    edits: tuple[Edit, ...]
    after: Draft  # examples unchanged: propose never approves examples itself
    fixes: tuple[int, ...]  # indices into `before.found` that are no longer problems
    still_open: tuple[int, ...]  # targeted indices that still are
    new: tuple[Found, ...]  # problems after that were not problems before
    broken: tuple[Example, ...]
    additions: Additions
    answered: bool | None  # every expected target's customer (each completion) now gets its outcome; else None
    attempts: int


@dataclass(frozen=True, slots=True)
class EditFailed:
    message: str


@dataclass(frozen=True, slots=True)
class Unextractable:
    message: str


type ProposeError = LLMError | EditFailed | Unextractable


def _still_a_problem(c: Compiled, f: Found) -> bool:
    match f:
        case Clash() | Gap():
            return _still(c, f)
        case OutrightConflict():
            return not isinstance(check(c, []), Sat)
        case GaveUp():
            return True
        case _:
            assert_never(f)


def _inputs(p: CheckedPolicy) -> set[str]:
    return {v.name for v in p.variables if not isinstance(v.role, Derived)}


def _customer_of(f: Found) -> Customer:
    match f:
        case Clash(customer=customer) | Gap(customer=customer):
            return customer
        case OutrightConflict() | GaveUp():
            return ()
        case _:
            assert_never(f)


def _witness_of(f: Found) -> Customer:
    match f:
        case Clash(witness=witness) | Gap(witness=witness):
            return witness
        case OutrightConflict() | GaveUp():
            return ()
        case _:
            assert_never(f)


def _rules_of(f: Found) -> tuple[str, ...]:
    match f:
        case OutrightConflict(rules) | Clash(rules=rules) | Gap(rules=rules):
            return rules
        case GaveUp():
            return ()
        case _:
            assert_never(f)


def _situation(state: Draft, before: Problems, target: Sequence[int], extra: Sequence[str] = ()) -> Situation:
    p = state.extraction.policy
    customer = tuple(dict.fromkeys(x for i in target for x in customer_phrases(p, _customer_of(before.found[i]))))
    rules = {r for i in target for r in _rules_of(before.found[i])} | set(extra)
    sentences = tuple(dict.fromkeys(link.anchor for link in state.extraction.links if link.rule in rules))
    return Situation(customer, sentences, tuple((o.name, outcome_label(o)) for o in p.outcomes))


def _sort_errors(errors: tuple[SortError | Changed, ...]) -> str:
    return "; ".join(str(e) for e in errors)


@dataclass(frozen=True, slots=True)
class _Tried:
    """An attempt that couldn't be checked: its edit didn't apply, or its rules didn't merge."""

    error: EditFailed | Unextractable


async def _evaluate(state: Draft, before: Problems, target: Sequence[int], edits: tuple[Edit, ...],
                    expected: Mapping[int, str], extractor: Extractor, attempts: int, *,
                    again: tuple[Anchor, ...] = (), guidance: str = "") -> Result[Proposal | _Tried, LLMError]:
    match apply(state.doc, edits):
        case Success(doc):
            pass
        case Failure(message):
            return Success(_Tried(EditFailed(message)))
        case _:
            unreachable()
    written = tuple(dict.fromkeys((*touched(state.doc, doc), *again)))
    replaced = gone(state.doc, doc)
    if written:
        match await extractor.extract(doc, vocabulary=state.extraction.policy, only=written, guidance=guidance):
            case Success(extracted):
                part = extracted
            case Failure(error):
                return Failure(error)
            case _:
                unreachable()
    else:
        part = Extraction(CheckedPolicy(replace(state.extraction.policy, rules=())), (), ())
    match merge(state.extraction, part, replaced):
        case Success(merged):
            pass
        case Failure(errors):
            return Success(_Tried(Unextractable(f"the new rules don't fit the policy: {_sort_errors(errors)}")))
        case _:
            unreachable()
    c1, c2 = compile(state.extraction.policy), compile(merged.policy)
    after = problems(c2)
    fixes = tuple(i for i, f in enumerate(before.found) if not _still_a_problem(c2, f))
    still_open = tuple(i for i in target if i not in fixes)
    new = tuple(f for f in after.found if not isinstance(f, GaveUp) and not _still_a_problem(c1, f))
    answered = (all(decides(c2, _customer_of(before.found[i]), o) for i, o in expected.items())
                if expected else None)
    return Success(Proposal(edits, Draft(doc, merged, state.examples), fixes, still_open, new,
                            broken(c2, state.examples), additions(state.extraction.policy, merged.policy),
                            answered, attempts))


def _clean(p: Proposal) -> bool:
    return not p.still_open and p.answered is not False and not p.new and not p.broken


def _cost(p: Proposal) -> int:
    return len(p.still_open) + len(p.new) + len(p.broken) + (p.answered is False)


def _what_went_wrong(state: Draft, before: Problems, p: Proposal, expected: Mapping[int, str]) -> str:
    policy = state.extraction.policy
    labels = {o.name: outcome_label(o) for o in policy.outcomes}
    lines = [f"Still a problem for: {', '.join(customer_phrases(policy, _customer_of(before.found[i])))}."
             for i in p.still_open]
    lines += [f"New problem for: {', '.join(customer_phrases(p.after.extraction.policy, _customer_of(f)))}."
              for f in p.new]
    lines += [f"Breaks approved example {ex.id}: it should get {labels.get(ex.outcome, ex.outcome)}."
              for ex in p.broken]
    if p.answered is False:
        c2 = compile(p.after.extraction.policy)
        lines += [f"The customer ({', '.join(customer_phrases(policy, _customer_of(before.found[i])))}) doesn't get "
                  f"{labels.get(o, o)}." for i, o in expected.items()
                  if not decides(c2, _customer_of(before.found[i]), o)]
    return "Your last change didn't work. " + " ".join(lines)


async def propose(state: Draft, before: Problems, target: tuple[int, ...], answer: Answer, *,
                  drafter: Drafter, extractor: Extractor, retries: int = 2, expect: Mapping[int, str] | None = None,
                  rules: tuple[str, ...] = ()) -> Result[Proposal, ProposeError]:
    """`expect` gives each target its own outcome (a group answered customer by customer); a `Choose` expects its
    outcome for every target. `rules` adds those rules' sentences to what the drafter is told, for findings that
    aren't in `before`."""
    situation = _situation(state, before, target, rules)
    match answer:
        case Choose(outcome):
            expected: Mapping[int, str] = dict.fromkeys(target, outcome) if expect is None else expect
        case Describe():
            expected = expect or {}
        case _:
            assert_never(answer)
    failure: str | None = None
    best: Proposal | None = None
    last: EditFailed | Unextractable | None = None
    for attempt in range(1, retries + 2):
        match await drafter.draft(state.doc, situation, answer, failure):
            case Success(edits):
                pass
            case Failure(error):
                return Failure(error)
            case _:
                unreachable()
        match await _evaluate(state, before, target, edits, expected, extractor, attempt):
            case Success(_Tried(error)):
                last, failure = error, f"Your last change couldn't be used: {error.message}"
            case Success(Proposal() as p):
                if _clean(p):
                    return Success(p)
                best = p if best is None or _cost(p) < _cost(best) else best
                failure = _what_went_wrong(state, before, p, expected)
            case Failure(error):
                return Failure(error)
            case _:
                unreachable()
    if best is not None:
        return Success(replace(best, attempts=retries + 1))
    assert last is not None
    return Failure(last)


async def reword(state: Draft, before: Problems, target: tuple[int, ...], edits: tuple[Edit, ...], *,
                 extractor: Extractor) -> Result[Proposal, ProposeError]:
    """The author's own wording, checked the same way, without the drafter."""
    return _checked(await _evaluate(state, before, target, edits, {}, extractor, 1))


async def extract_again(state: Draft, before: Problems, anchors: tuple[Anchor, ...], *, guidance: str,
                        extractor: Extractor) -> Result[Proposal, ProposeError]:
    """The document unchanged and these sentences extracted again with the author's guidance (a sentence nothing came
    from, which the author says decides something), checked like any proposal."""
    return _checked(await _evaluate(state, before, (), (), {}, extractor, 1, again=anchors, guidance=guidance))


def _checked(r: Result[Proposal | _Tried, LLMError]) -> Result[Proposal, ProposeError]:
    match r:
        case Success(_Tried(error)):
            return Failure(error)
        case Success(Proposal() as p):
            return Success(p)
        case Failure(error):
            return Failure(error)
        case _:
            unreachable()


def _example_id(customer: Customer, taken: set[str]) -> str:
    base = "-".join(f"{var}-{getattr(x, 'value', x)}" for var, x in customer).lower()
    base = re.sub(r"[^a-z0-9_-]+", "-", base).strip("-") or "example"
    out, n = base, 2
    while out in taken:
        out, n = f"{base}-{n}", n + 1
    return out


def approve(state: Draft, p: Proposal, before: Problems, answers: Mapping[int, str]) -> Result[Draft, str]:
    """The proposal's state, plus one approved example per fixed problem the author answered.

    An example's facts must prove its outcome (spec Calls 2), so the problem's customer is completed by Z3 with
    values that do, for any question the fix added. An answer the new policy can't give for that customer fails."""
    policy = p.after.extraction.policy
    c2 = compile(policy)
    inputs = frozenset(_inputs(policy))
    outcomes = {o.name for o in policy.outcomes}
    taken = {ex.id for ex in state.examples}
    added: list[Example] = []
    for i in sorted(answers):
        if i not in p.fixes:
            continue
        outcome = answers[i]
        if outcome not in outcomes:
            return Failure(f"the policy has no outcome {outcome!r}")
        given = [Cmp("eq", Var(v), x) for v, x in _witness_of(before.found[i]) if v in inputs]
        match decidable(c2, inputs, given=given, outcomes=[outcome]):
            case Sat(model):
                customer = tuple(sorted(model.items()))
            case _:
                return Failure(f"no customer like this one gets {outcome!r} under the changed policy")
        ex = Example(_example_id(_customer_of(before.found[i]), taken), customer, outcome)
        if not holds(c2, ex):
            return Failure(f"example {ex.id} doesn't decide {outcome!r} under the changed policy")
        taken.add(ex.id)
        added.append(ex)
    return Success(replace(p.after, examples=(*state.examples, *added)))
