"""Every problem and validator finding in the same style: a situation in plain words, what each rule involved says,
one question and its answers (spec, "Every kind of problem, in the same style"). Pure.

Formulas, variable names and solver words appear only in an item's `logic`. Contradictions, gaps and the checks
that gave up come from `core.problems`; validate's own `Conflict`, `NotTotal`, `Undecided` and its consistency,
totality and gap `SolverGaveUp` say the same thing and are left out.
"""
from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import assert_never

from policyproof.authoring.document import Anchor, Document
from policyproof.authoring.extraction import Extraction
from policyproof.authoring.plain import customer_phrases, name_words, outcome_label, phrase, verdict
from policyproof.core.problems import Clash, Customer, Found, Gap, GaveUp, OutrightConflict, Problems, groups, problems
from policyproof.core.render import pretty
from policyproof.core.semantics import free_vars, rule_expr
from policyproof.core.solver import Compiled, Label, RuleLabel, Sat, Unsat, check, compile, fact
from policyproof.core.syntax import BoolLit, CheckedPolicy, Derived, EnumLit, Expr, IntLit, Lit, Not, RealLit
from policyproof.core.validate import (
    Conflict,
    ConstraintRule,
    DefinitionToReview,
    DisjointGroups,
    Finding,
    ImpossibleInput,
    InputsRelated,
    NearDuplicate,
    NotTotal,
    OverlappingOutcomes,
    SolverGaveUp,
    Undecided,
    UnreachableOutcome,
    UnusedVariable,
    validate,
)
from policyproof.studio import wire as w
from policyproof.studio.view import numbers, rule_label, sentence_id
from policyproof.studio.workspace import Workspace

COVERED_BY_PROBLEMS = {"consistency", "totality", "undecided"}
QUESTION = "What should this customer get?"
THREE_OR_MORE = ("Any two of these rules work together. All of them at once can't, so no single rule is wrong. Your "
                 "answer decides which one changes.")
DEPENDS = w.Option("It depends on something else…", w.Describe("What does it depend on?", "It depends: "), False)
NOT_IN_DOCUMENT = "A rule added outside your document"


@dataclass(frozen=True, slots=True)
class Context:
    extraction: Extraction
    compiled: Compiled
    problems: Problems
    findings: tuple[Finding, ...]
    doc: Document
    workspace: Workspace
    titles: Mapping[Customer, str] = field(default_factory=dict)  # situation titles a model wrote
    sentences: Mapping[str, str] = field(default_factory=dict)  # sentences a model wrote for rules with none

    @staticmethod
    def of(extraction: Extraction, doc: Document, workspace: Workspace, *, titles: Mapping[Customer, str] | None = None,
           sentences: Mapping[str, str] | None = None) -> Context:
        c = compile(extraction.policy)
        return Context(extraction, c, problems(c), validate(c), doc, workspace, titles or {}, sentences or {})

    @property
    def policy(self) -> CheckedPolicy:
        return self.extraction.policy


@dataclass(frozen=True, slots=True)
class Entry:
    """An item and what the session needs to act on it."""

    item: w.Item
    problems: tuple[int, ...]  # indices into `Context.problems.found`
    rules: tuple[str, ...]
    names: tuple[str, ...]  # variables or outcomes it is about
    anchor: Anchor | None  # the sentence, for an uncovered sentence
    fingerprint: str


@dataclass(frozen=True, slots=True)
class Listing:
    entries: tuple[Entry, ...]
    groups: tuple[tuple[str, ...], ...]


def _lit(x: Lit) -> str:
    match x:
        case BoolLit(b):
            return "true" if b else "false"
        case IntLit(n):
            return str(n)
        case RealLit(q):
            return str(q)
        case EnumLit(_, value):
            return value
        case _:
            assert_never(x)


def _customer_key(customer: Customer) -> str:
    return ",".join(f"{v}={_lit(x)}" for v, x in customer)


def fingerprint(p: CheckedPolicy, key: str, rules: Sequence[str], names: Sequence[str]) -> str:
    """What a dismissal was about: the rules involved as they read now, and the names. A change to any of them makes
    the finding come back."""
    by_id = {r.id: r for r in p.rules}
    shape = [key, *(repr(rule_expr(by_id[r])) for r in sorted(rules) if r in by_id), *sorted(names)]
    return hashlib.sha256("\x00".join(shape).encode()).hexdigest()[:16]


class _Words:
    """Plain words for one context."""

    def __init__(self, ctx: Context) -> None:
        self.ctx = ctx
        self.p = ctx.policy
        self.nums = numbers(ctx.doc, ctx.extraction)
        self.variables = {v.name: v for v in self.p.variables}
        self.outcomes = {o.name: o for o in self.p.outcomes}
        self.by_id = {r.id: r for r in self.p.rules}
        self.anchors: dict[str, list[Anchor]] = {}
        for link in ctx.extraction.links:
            self.anchors.setdefault(link.rule, []).append(link.anchor)

    def label(self, rule: str) -> str:
        return rule_label(self.nums, rule)

    def sentence(self, rule: str) -> str:
        found = self.anchors.get(rule)
        return " ".join(a.text for a in found) if found else self.ctx.sentences.get(rule, NOT_IN_DOCUMENT)

    def sentence_ids(self, rules: Sequence[str]) -> tuple[str, ...]:
        return tuple(dict.fromkeys(sentence_id(a) for r in rules for a in self.anchors.get(r, [])))

    def name(self, var: str) -> str:
        v = self.variables.get(var)
        text = (v.description if v is not None and v.description else name_words(var)).rstrip(".")
        return f"“{text[:1].lower()}{text[1:]}”"

    def outcome(self, name: str) -> str:
        o = self.outcomes.get(name)
        return outcome_label(o) if o is not None else name_words(name)

    def lower(self, name: str) -> str:
        label = self.outcome(name)
        return label[:1].lower() + label[1:]

    def facts(self, customer: Customer) -> tuple[str, ...]:
        return customer_phrases(self.p, customer)

    def title(self, customer: Customer, fallback: str) -> str:
        if customer in self.ctx.titles:
            return self.ctx.titles[customer]
        phrases = self.facts(customer)
        if not phrases:
            return fallback
        return phrases[0] + "".join(f", {x[:1].lower()}{x[1:]}" for x in phrases[1:])

    def logic(self, rules: Sequence[str], extra: Sequence[str] = ()) -> tuple[str, ...]:
        return (*(f"{self.label(r)} ({r}):  {pretty(rule_expr(self.by_id[r]))}" for r in rules if r in self.by_id),
                *extra)

    def verdicts(self, rules: Sequence[str], says: str, tone: w.Tone = "none") -> tuple[w.Verdict, ...]:
        return tuple(w.Verdict(self.label(r), self.sentence(r), says, tone) for r in rules)

    def inputs_of(self, model: Mapping[str, Lit]) -> Customer:
        return tuple(sorted((v, x) for v, x in model.items()
                            if v in self.variables and not isinstance(self.variables[v].role, Derived)))

    def core(self, assertions: Sequence[tuple[Label, Expr]]) -> tuple[str, ...]:
        result = check(self.ctx.compiled, assertions)
        if not isinstance(result, Unsat):
            return ()
        ids = {label.id for label in result.core if isinstance(label, RuleLabel)}
        return tuple(r.id for r in self.p.rules if r.id in ids)

    def outcome_options(self, names: Sequence[str], *, secondary: bool) -> tuple[w.Option, ...]:
        return tuple(w.Option(self.outcome(n), w.Choose(n), secondary) for n in names)


def _item(key: str, kind: w.ItemKind, level: w.Level, title: str, *, facts: tuple[str, ...] = (),
          lead: str | None = None, verdicts: tuple[w.Verdict, ...] = (), note: str | None = None,
          question: str | None = None, options: tuple[w.Option, ...] = (), sentences: tuple[str, ...] = (),
          logic: tuple[str, ...] = ()) -> w.Item:
    return w.Item(key, kind, level, title, facts, lead, verdicts, note, question, options, sentences, logic, False,
                  None)


def _pointed(t: _Words, clash: Clash) -> list[str]:
    """The outcomes the clashing rules point to, in policy order."""
    labels = {verdict(t.p, s)[0] for s in clash.says}
    return [o.name for o in t.p.outcomes if outcome_label(o) in labels]


def _something_else(t: _Words, shown: Sequence[str]) -> tuple[w.Option, ...]:
    others = [o.name for o in t.p.outcomes if o.name not in shown]
    return (w.Option("Something else…", w.Describe(QUESTION, "This customer should get: "), False),
            *t.outcome_options(others, secondary=True))


def _clash(t: _Words, i: int, f: Clash) -> Entry:
    key = "clash:" + "+".join(f.rules)
    pointed = _pointed(t, f)
    said = {s.rule: verdict(t.p, s) for s in f.says}
    two = len(f.rules) == 2
    item = _item(key, "clash", "error", t.title(f.customer, "Every customer"), facts=t.facts(f.customer),
                 lead="Two rules give opposite answers for this customer:" if two
                 else f"These {len(f.rules)} rules can't all be followed for this customer:",
                 verdicts=tuple(w.Verdict(t.label(r), t.sentence(r), *said[r]) for r in f.rules),
                 note=None if two else THREE_OR_MORE, question=QUESTION,
                 options=(*t.outcome_options(pointed, secondary=False), *_something_else(t, pointed), DEPENDS),
                 sentences=t.sentence_ids(f.rules),
                 logic=t.logic(f.rules, (f"Z3 example:  {_customer_key(f.witness)}  ⇒  no answer meets every rule",)))
    return Entry(item, (i,), f.rules, (), None, fingerprint(t.p, key, f.rules, ()))


def _conflict(t: _Words, i: int, f: OutrightConflict) -> Entry:
    key = "conflict:" + "+".join(f.rules)
    options = tuple(w.Option(f"{t.label(r)} is right", w.Describe(
        "", f"{t.label(r)} is right: “{t.sentence(r)}” Change or remove the other sentences so they agree with it."),
        False) for r in f.rules)
    item = _item(key, "conflict", "error", "These rules contradict each other for every customer",
                 lead="They can't all be true at once, whatever the facts:",
                 verdicts=t.verdicts(f.rules, "Always applies"), question="Which of these is true?", options=options,
                 sentences=t.sentence_ids(f.rules), logic=t.logic(f.rules))
    return Entry(item, (i,), f.rules, (), None, fingerprint(t.p, key, f.rules, ()))


def _gap(t: _Words, i: int, f: Gap) -> Entry:
    key = "gap:" + _customer_key(f.customer)
    everyone = [o.name for o in t.p.outcomes]
    options = (*t.outcome_options(everyone, secondary=False),
               w.Option("Something else…", w.Describe(QUESTION, "This customer should get: "), False),
               w.Option("A person should decide this one", w.Dismiss("A person decides cases like this"), False))
    title = t.ctx.titles.get(f.customer) or ("Nothing in the policy says what happens to this customer"
                                             if f.customer else "Nothing in the policy says what any customer gets")
    item = _item(key, "gap", "warning", title, facts=t.facts(f.customer),
                 lead="No rule decides what this customer gets.", question=QUESTION, options=options,
                 sentences=t.sentence_ids(f.rules),
                 logic=t.logic(f.rules, (f"Z3 example:  {_customer_key(f.witness)}  ⇒  no outcome is proven",)))
    return Entry(item, (i,), f.rules, (), None, fingerprint(t.p, key, f.rules, ()))


def _gave_up(key: str, check_name: str, reason: str) -> Entry:
    item = _item(key, "gave_up", "error", "This part of the policy is too complex to check",
                 lead="The solver couldn't finish this check, so it doesn't count as passing.",
                 logic=(f"check: {check_name}", f"reason: {reason}"))
    return Entry(item, (), (), (), None, "")


def _problem(t: _Words, i: int, f: Found) -> Entry:
    match f:
        case Clash():
            return _clash(t, i, f)
        case OutrightConflict():
            return _conflict(t, i, f)
        case Gap():
            return _gap(t, i, f)
        case GaveUp(check_name, reason):
            return _gave_up(f"gave_up:{check_name}", check_name, reason)
        case _:
            assert_never(f)


def _uncovered(t: _Words, a: Anchor) -> Entry:
    sid = sentence_id(a)
    item = _item(f"uncovered:{sid}", "uncovered", "uncovered", "Nothing was taken from this sentence",
                 lead=f"“{a.text}”", question="Should this decide what customers get, or is it background information?",
                 options=(w.Option("It decides what customers get", w.Decides(), False),
                          w.Option("It's background information", w.Background(), False)), sentences=(sid,))
    return Entry(item, (), (), (), a, "")


def _mentions(t: _Words, names: Sequence[str]) -> tuple[str, ...]:
    return tuple(r.id for r in t.p.rules if free_vars(rule_expr(r)) & set(names))


def _entry(t: _Words, key: str, kind: w.ItemKind, level: w.Level, title: str, rules: tuple[str, ...],
           names: tuple[str, ...], question: str, options: tuple[w.Option, ...], *, facts: tuple[str, ...] = (),
           lead: str | None = None, says: str | None = None, tone: w.Tone = "none",
           logic: tuple[str, ...] = ()) -> Entry:
    item = _item(key, kind, level, title, facts=facts, lead=lead,
                 verdicts=t.verdicts(rules, says, tone) if says is not None else (), question=question,
                 options=options, sentences=t.sentence_ids(rules), logic=t.logic(rules, logic))
    return Entry(item, (), rules, names, None, fingerprint(t.p, key, rules, names))


def _yes_no(yes: str, yes_action: w.Action, no: str, no_action: w.Action) -> tuple[w.Option, ...]:
    return (w.Option(yes, yes_action, False), w.Option(no, no_action, False))


def _finding(t: _Words, f: Finding) -> Entry | None:
    c = t.ctx.compiled
    match f:
        case Conflict() | NotTotal() | Undecided():
            return None
        case SolverGaveUp(check_name, reason):
            return None if check_name in COVERED_BY_PROBLEMS else _gave_up(f"gave_up:{check_name}", check_name, reason)
        case NearDuplicate(a, b):
            return _entry(t, f"near:{a}+{b}", "near_duplicate", "warning",
                          f"These look like the same thing: {t.name(a)} and {t.name(b)}", _mentions(t, (a, b)),
                          (a, b), "Are they the same?",
                          _yes_no("Yes, they're the same", w.Same(), "No, they're different",
                                  w.Different("How do they differ?")), says="Uses one of them", logic=(f"{a} ~ {b}",))
        case UnusedVariable(var):
            return _entry(t, f"unused:{var}", "unused", "warning", f"Nothing in the rules uses {t.name(var)}", (),
                          (var,), "Is this part of the policy?",
                          _yes_no("No, remove it", w.RemoveName(), "Yes, keep it",
                                  w.Dismiss("It is part of the policy")), logic=(f"unused: {var}",))
        case DisjointGroups(gs):
            rest = tuple(r for g in gs[1:] for r in g)
            return _entry(t, "disjoint:" + "|".join("+".join(g) for g in gs), "disjoint", "warning",
                          "These rules share nothing with the rest of the policy", rest, (),
                          "Are they part of the same policy?",
                          _yes_no("Yes, they're a separate topic", w.Dismiss("They are a separate topic"),
                                  "They're about the same thing as the rest",
                                  w.Describe("How are they connected?", "These rules are about the same thing as the "
                                                                        "rest of the policy: ")),
                          lead="No name they use appears in the other rules:", says="Shares nothing")
        case ImpossibleInput(var, value):
            what = phrase(t.variables[var], value)
            rules = t.core([fact(var, value)])
            return _entry(t, f"impossible:{var}={_lit(value)}", "impossible", "error",
                          f"The rules say this can never happen: {what[:1].lower()}{what[1:]}", rules, (var,),
                          "Is that intended?",
                          _yes_no("Yes, it can't happen", w.Dismiss("It can't happen"), "No, it can happen",
                                  w.Describe("", f"It can happen that {what[:1].lower()}{what[1:]}. Change the rule "
                                                 "that rules it out.")),
                          says="Rules it out", tone="no", logic=(f"{var} = {_lit(value)}  ⇒  no rule set holds",))
        case UnreachableOutcome(name):
            o = t.outcomes[name]
            rules = t.core([fact(v, x) for v, x in o.assignment])
            return _entry(t, f"unreachable:{name}", "unreachable", "error",
                          f"No customer can ever get {t.lower(name)}", rules, (name,), "Is that intended?",
                          _yes_no("Yes, nobody gets it", w.Dismiss("Nobody gets it"), "No, some customers should",
                                  w.Describe("Who should get it?", f"These customers should get {t.lower(name)}: ")),
                          says="Rules it out", tone="no")
        case OverlappingOutcomes(a, b):
            both = [fact(v, x) for n in (a, b) for v, x in t.outcomes[n].assignment]
            result = check(c, both)
            customer = t.inputs_of(result.model) if isinstance(result, Sat) else ()
            return _entry(t, f"overlap:{a}+{b}", "overlap", "review",
                          f"A customer who gets both {t.lower(a)} and {t.lower(b)}", (), (a, b),
                          "Should anyone get both?",
                          _yes_no("Yes, that's fine", w.Dismiss("Some customers get both"), "No, never both",
                                  w.Describe("", f"No customer should get both {t.lower(a)} and {t.lower(b)}.")),
                          facts=t.facts(customer))
        case InputsRelated(rule):
            broken = check(c, [(RuleLabel(rule), Not(rule_expr(t.by_id[rule])))], rules=False)
            customer = t.inputs_of(broken.model) if isinstance(broken, Sat) else ()
            return _entry(t, f"inputs:{rule}", "inputs_related", "review",
                          f"{t.label(rule)} says some facts can never go together", (rule,), (),
                          "Can this really never happen?",
                          _yes_no("Yes, it can never happen", w.Dismiss("It can never happen"), "No, it can happen",
                                  w.Describe("What should happen then?", "This can happen. ")),
                          facts=t.facts(customer), lead="A customer like this would break it:", says="Never happens")
        case DefinitionToReview(rule) | ConstraintRule(rule):
            kind: w.ItemKind = "definition" if isinstance(f, DefinitionToReview) else "constraint"
            return _entry(t, f"{kind}:{rule}", kind, "review", f"“{t.sentence(rule)}”", (rule,), (),
                          "Is that exactly right?",
                          _yes_no("Yes, exactly", w.Dismiss("Exactly right"), "No",
                                  w.Describe("What's wrong with it?", "This sentence isn't quite right: ")),
                          lead=f"{t.label(rule)}, read as: this, and only this.")
        case _:
            assert_never(f)


def _unlinked(t: _Words, rule: str) -> Entry:
    return _entry(t, f"unlinked:{rule}", "unlinked", "review", "A rule that isn't in your document", (rule,), (),
                  "Add this to the document?",
                  _yes_no("Yes, add it", w.AddSentence(), "No, leave it out", w.Dismiss(None)),
                  lead=f"“{t.sentence(rule)}”")


RANK: dict[w.ItemKind, int] = {"clash": 0, "conflict": 0, "gave_up": 1, "gap": 2, "impossible": 3, "unreachable": 3,
                               "uncovered": 4, "near_duplicate": 5, "unused": 5, "disjoint": 5, "overlap": 6,
                               "inputs_related": 6, "definition": 6, "constraint": 6, "unlinked": 7}
UNDISMISSABLE: frozenset[w.ItemKind] = frozenset({"clash", "conflict", "gave_up", "uncovered"})


def items(ctx: Context, *, new_keys: frozenset[str] = frozenset()) -> Listing:
    """What the author still has to decide, worst first; problems that share rules sit together."""
    t = _Words(ctx)
    found = ctx.problems.found
    by_group = [i for g in groups(found) for i in g]
    background = set(ctx.workspace.background)
    entries = [_problem(t, i, found[i]) for i in by_group]
    entries += [_uncovered(t, a) for a in ctx.extraction.uncovered if a not in background]
    entries += [e for f in ctx.findings if (e := _finding(t, f)) is not None]
    linked = {link.rule for link in ctx.extraction.links}
    entries += [_unlinked(t, r.id) for r in ctx.policy.rules if r.id not in linked]
    entries.sort(key=lambda e: RANK[e.item.kind])  # stable: clashes stay in group order
    dismissed = {d.key: d for d in ctx.workspace.dismissed}
    out: list[Entry] = []
    for e in dict((e.item.key, e) for e in entries).values():
        d = dismissed.get(e.item.key)
        if d is not None and e.item.kind not in UNDISMISSABLE:
            if d.fingerprint == e.fingerprint:
                continue
            e = replace(e, item=replace(e.item, dismissed_before=d.reason))
        if e.item.key in new_keys:
            e = replace(e, item=replace(e.item, new=True))
        out.append(e)
    keys_of = {i: e.item.key for e in out for i in e.problems}
    grouped = tuple(ks for g in groups(found) if len(ks := tuple(dict.fromkeys(keys_of[i] for i in g if i in keys_of)))
                    > 1)
    return Listing(tuple(out), grouped)
