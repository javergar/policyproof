"""The studio's operations over one document: what each request does to the files, checked by the authoring layer
before anything is written. Every change is written straight away and can be undone (spec Calls 3).

A proposal remembers the version of the policy it was made on; accepting it after anything else changed, or after
the document changed on disk, is refused, so an author's change in their own editor is never overwritten.
"""
from __future__ import annotations

import asyncio
import itertools
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import assert_never

from returns.result import Failure, Result, Success

from policyproof.authoring.document import Anchor, Document, Edit, Insert, Remove, Replace, apply, parse, touched
from policyproof.authoring.examples import broken
from policyproof.authoring.extraction import Extraction, Link
from policyproof.authoring.merge import Additions, merge, rename, rule_changes
from policyproof.authoring.plain import customer_phrases, name_words, outcome_label
from policyproof.authoring.ports import Answer, Choose, Describe, Drafter, Extractor, Phraser
from policyproof.authoring.propose import (
    Draft,
    EditFailed,
    Proposal,
    ProposeError,
    Unextractable,
    approve,
    extract_again,
    propose,
    reword,
)
from policyproof.core._result import unreachable
from policyproof.core.problems import Clash, Customer, Found, Gap, GaveUp, OutrightConflict, Problems, decides
from policyproof.core.render import pretty
from policyproof.core.semantics import rule_expr
from policyproof.core.solver import compile
from policyproof.core.syntax import Ask, CheckedPolicy, Rule, System, Variable
from policyproof.core.typecheck import check_policy
from policyproof.effects.errors import LLMError, describe
from policyproof.studio import wire as w
from policyproof.studio.items import Context, Entry, Listing, items
from policyproof.studio.view import doc_view, numbers, rule_label
from policyproof.studio.workspace import (
    Dismissal,
    Files,
    Paths,
    Workspace,
    can_undo,
    digest,
    load,
    load_snapshot,
    pop_undo,
    push_undo,
    save,
    save_snapshot,
)

NEEDS_MODEL = "Start the studio with --model to {}."
DECIDES = "This sentence decides what customers get: extract the rules it states."


@dataclass(frozen=True, slots=True)
class Ports:
    extractor: Extractor | None = None
    drafter: Drafter | None = None
    phraser: Phraser | None = None

    @property
    def model(self) -> bool:
        return self.extractor is not None and self.drafter is not None


@dataclass(frozen=True, slots=True)
class _Open:
    """A proposal the author hasn't accepted yet."""

    proposal: Proposal
    before: Problems
    targets: tuple[int, ...]
    expected: dict[int, str]
    titles: dict[int, str]  # the title of each problem of `before` that has an item
    keys: frozenset[str]  # the item keys before
    version: int


@dataclass(frozen=True, slots=True)
class _Reextract:
    files: Files  # as on disk, links re-found in the document's current text
    new: Extraction
    anchors: tuple[Anchor, ...]  # per diff
    version: int


def _error(e: ProposeError | LLMError | str) -> w.ErrorReply:
    match e:
        case str():
            return w.ErrorReply(e)
        case EditFailed(message) | Unextractable(message):
            return w.ErrorReply(f"The proposed change couldn't be used: {message}")
        case _:
            return w.ErrorReply(f"The model call failed: {describe(e)}")


def _found_customer(f: Found) -> Customer:
    match f:
        case Clash(customer=customer) | Gap(customer=customer):
            return customer
        case OutrightConflict() | GaveUp():
            return ()
        case _:
            assert_never(f)


def _found_witness(f: Found) -> Customer:
    match f:
        case Clash(witness=witness) | Gap(witness=witness):
            return witness
        case OutrightConflict() | GaveUp():
            return ()
        case _:
            assert_never(f)


def _role(v: Variable) -> w.Switch | None:
    match v.role:
        case Ask(question):
            return w.Switch(v.name, question, "ask")
        case System():
            return w.Switch(v.name, v.description or name_words(v.name), "system")
        case _:
            return None


def _additions(a: Additions) -> tuple[str, ...]:
    out: list[str] = []
    for v in a.variables:
        match v.role:
            case Ask(question):
                out.append(f"The agent will now ask customers: {question}")
            case System():
                out.append(f"It will come from your systems: {(v.description or name_words(v.name)).rstrip('.')}")
            case _:
                out.append(f"A new term: {(v.description or name_words(v.name)).rstrip('.')}")
    out += [f"{name_words(sort)} can now also be {value}" for sort, value in a.values]
    out += [f"A new outcome: {outcome_label(o)}" for o in a.outcomes]
    return tuple(out)


def _switched(v: Variable) -> Variable:
    match v.role:
        case Ask():
            return replace(v, role=System())
        case System():
            text = (v.description or name_words(v.name)).rstrip(".?")
            return replace(v, role=Ask(f"{text}?"))
        case _:
            return v


def _changes(edits: Sequence[Edit]) -> tuple[w.Change, ...]:
    out: list[w.Change] = []
    for e in edits:
        match e:
            case Replace(at, text):
                out.append(w.Change("replace", at.section, at.text, text))
            case Insert(section, _, text):
                out.append(w.Change("insert", section, None, text))
            case Remove(at):
                out.append(w.Change("remove", at.section, at.text, None))
            case _:
                assert_never(e)
    return tuple(out)


def _reworded(edits: Sequence[Edit], texts: Sequence[str | None]) -> tuple[Edit, ...]:
    out: list[Edit] = []
    for e, t in itertools.zip_longest(edits, texts):
        if e is None:
            break
        match e:
            case Replace(at, _) if t is not None:
                out.append(Replace(at, t))
            case Insert(section, after, _) if t is not None:
                out.append(Insert(section, after, t))
            case _:
                out.append(e)
    return tuple(out)


def _quoted(titles: Sequence[str]) -> str:
    return " and ".join(f"“{t}”" for t in titles)


class Session:
    """One document's files and what the author is doing with them. Not safe to share between tasks without the
    `Studio`'s lock."""

    def __init__(self, paths: Paths, ports: Ports, files: Files) -> None:
        self.paths, self.ports, self.files = paths, ports, files
        self.version = 0
        self.seen = digest(files.text)
        self.new_keys: frozenset[str] = frozenset()
        self.banner: w.Banner | None = None
        self.proposals: dict[str, _Open] = {}
        self.reextracts: dict[str, _Reextract] = {}
        self.titles: dict[Customer, str] = {}
        self.sentences: dict[str, str] = {}
        self._ids = itertools.count(1)
        self.ctx: Context = Context.of(files.extraction, parse(files.text), files.workspace)
        self.listing: Listing = items(self.ctx)

    # ---- opening and refreshing

    @staticmethod
    async def open(paths: Paths, ports: Ports) -> Result[Session, str]:
        match load(paths):
            case Success(None):
                if ports.extractor is None:
                    return Failure(f"There is no policy for {paths.doc.name} yet. " + NEEDS_MODEL.format("extract one"))
                text = paths.doc.read_text()
                match await ports.extractor.extract(parse(text)):
                    case Success(ex):
                        files = Files(text, ex, (), Workspace.empty(text))
                        save(paths, files)
                        save_snapshot(paths, ex)
                    case Failure(e):
                        return Failure(f"The extraction failed: {describe(e)}")
                    case _:
                        unreachable()
            case Success(Files() as files):
                if load_snapshot(paths) is None:
                    save_snapshot(paths, files.extraction)
            case Failure(message):
                return Failure(message)
            case _:
                unreachable()
        s = Session(paths, ports, files)
        await s.refresh()
        return Success(s)

    async def _phrase(self, ctx: Context) -> None:
        """Situation titles and sentences for rules with none, from the model when there is one; cached."""
        phraser = self.ports.phraser
        if phraser is None:
            return
        p = ctx.policy
        for f in ctx.problems.found:
            customer = _found_customer(f)
            if isinstance(f, Clash | Gap) and customer and customer not in self.titles:
                match await phraser.title(p, customer_phrases(p, customer)):
                    case Success(title):
                        self.titles[customer] = title
                    case _:
                        pass
        linked = {link.rule for link in ctx.extraction.links}
        for r in p.rules:
            if r.id not in linked and r.id not in self.sentences:
                match await phraser.sentence(p, r):
                    case Success(text):
                        self.sentences[r.id] = text
                    case _:
                        pass

    async def refresh(self) -> None:
        ctx = Context.of(self.files.extraction, parse(self.files.text), self.files.workspace)
        await self._phrase(ctx)
        self.ctx = replace(ctx, titles=dict(self.titles), sentences=dict(self.sentences))
        self.listing = items(self.ctx, new_keys=self.new_keys)

    # ---- reading

    def _outside(self) -> bool:
        return not self.paths.doc.exists() or digest(self.paths.doc.read_text()) != self.seen

    def outside(self) -> w.OutsideReply:
        return w.OutsideReply(self._outside())

    def view(self) -> w.StateReply:
        f, ctx = self.files, self.ctx
        p = f.extraction.policy
        entries = [e.item for e in self.listing.entries]
        open_rules = {r for e in self.listing.entries if e.item.kind in ("clash", "conflict") for r in e.rules}
        doc = doc_view(self.paths.doc.name, ctx.doc, parse(f.workspace.baseline), f.extraction, f.workspace,
                       open_rules)
        labels = {o.name: outcome_label(o) for o in p.outcomes}
        examples = tuple(w.ExampleView(ex.id, customer_phrases(p, ex.customer), labels.get(ex.outcome, ex.outcome))
                         for ex in f.examples)
        return w.StateReply(w.SessionView(self.paths.doc.name, doc, tuple(entries), self.listing.groups,
                                          len(entries), len(f.workspace.fixed), examples, self.banner,
                                          can_undo(self.paths), self.ports.model, self._outside(), not entries,
                                          self.version))

    def _entry(self, key: str) -> Entry | None:
        return next((e for e in self.listing.entries if e.item.key == key), None)

    def _draft(self) -> Draft:
        return Draft(self.ctx.doc, self.files.extraction, self.files.examples)

    # ---- changing the files

    async def _write(self, files: Files, banner: w.Banner | None, new_keys: frozenset[str] = frozenset(),
                     *, undoable: bool = True) -> w.StateReply:
        if undoable:
            push_undo(self.paths, self.files)
        save(self.paths, files)
        self.files, self.seen = files, digest(files.text)
        self.version += 1
        self.banner, self.new_keys = banner, new_keys
        self.proposals.clear()
        self.reextracts.clear()
        await self.refresh()
        return self.view()

    def _with_workspace(self, change: Callable[[Workspace], Workspace]) -> Files:
        return replace(self.files, workspace=change(self.files.workspace))

    def _guard(self, version: int) -> w.ErrorReply | None:
        if version != self.version:
            return w.ErrorReply("The policy changed since this was proposed. Choose again.")
        if self._outside():
            return w.ErrorReply("The document changed on disk. Use “Extract again” before accepting changes.")
        return None

    # ---- answering

    async def answer(self, req: w.AnswerRequest) -> w.Reply:
        entry = self._entry(req.key)
        if entry is None or not 0 <= req.option < len(entry.item.options):
            return w.ErrorReply("That question is no longer open.")
        action = entry.item.options[req.option].action
        text = req.text.strip()
        match action:
            case w.Choose(outcome):
                return await self._propose(entry, Choose(outcome), {i: outcome for i in entry.problems})
            case w.Describe(prompt, prefix):
                if prompt and not text:
                    return w.ErrorReply("Say it in a sentence first.")
                return await self._propose(entry, Describe(prefix + text), {})
            case w.Dismiss(reason):
                return await self.dismiss(w.DismissRequest(req.key, reason or text))
            case w.Background():
                anchor = entry.anchor
                if anchor is None:
                    return w.ErrorReply("That isn't a sentence.")
                return await self._write(self._with_workspace(
                    lambda ws: replace(ws, background=(*ws.background, anchor))), None)
            case w.Decides():
                if entry.anchor is None or self.ports.extractor is None:
                    return w.ErrorReply(NEEDS_MODEL.format("extract this sentence"))
                r = await extract_again(self._draft(), self.ctx.problems, (entry.anchor,), guidance=DECIDES,
                                        extractor=self.ports.extractor)
                return self._register(r, entry, (), {})
            case w.Same():
                return await self._same(entry)
            case w.Different():
                if not text:
                    return w.ErrorReply("Say how they differ first.")
                return await self._different(entry, text)
            case w.RemoveName():
                return await self._remove_name(entry)
            case w.AddSentence():
                return await self._add_sentence(entry)
            case _:
                assert_never(action)

    async def answer_group(self, req: w.GroupRequest) -> w.Reply:
        """One proposal for several customers, each with its own answer."""
        parts: list[str] = []
        targets: list[int] = []
        rules: list[str] = []
        expected: dict[int, str] = {}
        p = self.ctx.policy
        labels = {o.name: outcome_label(o) for o in p.outcomes}
        for a in req.answers:
            entry = self._entry(a.key)
            if entry is None or not 0 <= a.option < len(entry.item.options):
                return w.ErrorReply("One of those questions is no longer open.")
            who = ", ".join(entry.item.facts) or entry.item.title
            match entry.item.options[a.option].action:
                case w.Choose(outcome):
                    parts.append(f"a customer with {who} should get {labels.get(outcome, outcome)}")
                    expected.update(dict.fromkeys(entry.problems, outcome))
                case w.Describe(prompt, prefix):
                    if prompt and not a.text.strip():
                        return w.ErrorReply("Say it in a sentence first.")
                    parts.append(f"for a customer with {who}: {prefix}{a.text.strip()}")
                case _:
                    return w.ErrorReply("Answer each customer with what they should get, or decide them one by one.")
            targets += entry.problems
            rules += entry.rules
        if not parts:
            return w.ErrorReply("Answer at least one customer.")
        entry0 = self._entry(req.answers[0].key)
        assert entry0 is not None
        group = Entry(entry0.item, tuple(dict.fromkeys(targets)), tuple(dict.fromkeys(rules)), (), None, "")
        return await self._propose(group, Describe("Decide these customers together: " + "; ".join(parts) + "."),
                                   expected)

    async def _propose(self, entry: Entry, answer: Answer, expected: dict[int, str]) -> w.Reply:
        if self.ports.drafter is None or self.ports.extractor is None:
            return w.ErrorReply(NEEDS_MODEL.format("propose changes"))
        r = await propose(self._draft(), self.ctx.problems, entry.problems, answer, drafter=self.ports.drafter,
                          extractor=self.ports.extractor, expect=expected or None,
                          rules=() if entry.problems else entry.rules)
        return self._register(r, entry, entry.problems, expected)

    def _register(self, r: Result[Proposal, ProposeError], entry: Entry, targets: tuple[int, ...],
                  expected: dict[int, str]) -> w.Reply:
        match r:
            case Success(proposal):
                pass
            case Failure(e):
                return _error(e)
            case _:
                unreachable()
        titles = {i: e.item.title for e in self.listing.entries for i in e.problems}
        o = _Open(proposal, self.ctx.problems, targets, expected, titles,
                  frozenset(e.item.key for e in self.listing.entries), self.version)
        pid = f"p{next(self._ids)}"
        self.proposals[pid] = o
        return w.ProposalReply(self._proposal_view(pid, o))

    def _proposal_view(self, pid: str, o: _Open) -> w.ProposalView:
        p = o.proposal
        before_policy, after_policy = self.ctx.policy, p.after.extraction.policy
        labels = {x.name: outcome_label(x) for x in after_policy.outcomes}
        checks: list[w.Check] = []
        if not p.edits:
            checks.append(w.Check("ok", "The document stays as it is; the sentence becomes a rule."))
        fixed = [o.titles.get(i, "a problem") for i in p.fixes]
        if fixed:
            checks.append(w.Check("ok", f"Fixes {_quoted(fixed)}."))
        if p.still_open:
            checks.append(w.Check("open", f"Still open after this: {_quoted([o.titles.get(i, 'a problem')
                                                                              for i in p.still_open])}."))
        if p.answered is False:
            checks.append(w.Check("warn", "The customer still doesn't get the answer you chose."))
        if p.new:
            new = [", ".join(customer_phrases(after_policy, _found_customer(f))) or "every customer" for f in p.new]
            checks.append(w.Check("warn", f"This wording causes a new problem for {_quoted(new)}. You can accept it "
                                          "and decide that next, or keep editing."))
        else:
            checks.append(w.Check("ok", "Checked against every rule: nothing new conflicts."))
        if p.broken:
            for ex in p.broken:
                checks.append(w.Check("warn", f"The approved example customer “{', '.join(customer_phrases(
                    before_policy, ex.customer))}” would no longer get {labels.get(ex.outcome, ex.outcome)}."))
        elif self.files.examples:
            n = len(self.files.examples)
            checks.append(w.Check("ok", f"All {n} example customers you approved still get the same answer." if n > 1
                                  else "The example customer you approved still gets the same answer."))
        switches = tuple(s for v in p.additions.variables if (s := _role(v)) is not None)
        return w.ProposalView(pid, _changes(p.edits), tuple(checks), _additions(p.additions), switches,
                              bool(p.new or p.broken), p.attempts)

    async def reword(self, req: w.RewordRequest) -> w.Reply:
        o = self.proposals.get(req.proposal)
        if o is None:
            return w.ErrorReply("That proposal is no longer open.")
        if (guard := self._guard(o.version)) is not None:
            return guard
        if self.ports.extractor is None:
            return w.ErrorReply(NEEDS_MODEL.format("check your wording"))
        edits = _reworded(o.proposal.edits, req.texts)
        r = await reword(self._draft(), o.before, o.targets, edits, extractor=self.ports.extractor)
        match r:
            case Success(p):
                c2 = compile(p.after.extraction.policy)
                answered = (all(decides(c2, _found_customer(o.before.found[i]), x) for i, x in o.expected.items())
                            if o.expected else None)
                p = replace(p, answered=answered)
                pid = f"p{next(self._ids)}"
                self.proposals[pid] = replace(o, proposal=p)
                return w.ProposalReply(self._proposal_view(pid, self.proposals[pid]))
            case Failure(e):
                return _error(e)
            case _:
                unreachable()

    async def accept(self, req: w.AcceptRequest) -> w.Reply:
        o = self.proposals.get(req.proposal)
        if o is None:
            return w.ErrorReply("That proposal is no longer open.")
        if (guard := self._guard(o.version)) is not None:
            return guard
        p = o.proposal
        added = {v.name for v in p.additions.variables}
        policy = p.after.extraction.policy
        if req.switch:
            switched = replace(policy, variables=tuple(_switched(v) if v.name in req.switch and v.name in added
                                                       else v for v in policy.variables))
            match check_policy(switched):
                case Success(checked):
                    p = replace(p, after=replace(p.after, extraction=replace(p.after.extraction, policy=checked)))
                case Failure(errors):
                    return w.ErrorReply("; ".join(str(e) for e in errors))
                case _:
                    unreachable()
        c2 = compile(p.after.extraction.policy)
        answers = {i: o.expected[i] for i in p.fixes if i in o.expected and i in o.targets}
        for i in p.fixes:  # an example only for what the author answered, not for what the change also fixed
            if i in o.targets and i not in answers and isinstance(o.before.found[i], Clash | Gap):
                witness = _found_witness(o.before.found[i])
                got = next((x.name for x in p.after.extraction.policy.outcomes if decides(c2, witness, x.name)), None)
                if got is not None:
                    answers[i] = got
        match approve(self._draft(), p, o.before, answers):
            case Success(draft):
                pass
            case Failure(message):
                return w.ErrorReply(f"The change can't be saved: {message}")
            case _:
                unreachable()
        fixed = tuple(o.titles[i] for i in p.fixes if i in o.titles)
        files = Files(draft.doc.text, draft.extraction, draft.examples,
                      replace(self.files.workspace, fixed=(*self.files.workspace.fixed, *fixed)))
        changed = self._changed_labels(draft.doc, draft.extraction)
        await self._write(files, None)
        self.new_keys = frozenset({e.item.key for e in self.listing.entries} - o.keys)
        self.listing = items(self.ctx, new_keys=self.new_keys)
        new_titles = tuple(e.item.title for e in self.listing.entries if e.item.key in self.new_keys)
        self.banner = w.Banner(fixed, new_titles, changed)
        return self.view()

    def _changed_labels(self, doc: Document, ex: Extraction) -> tuple[str, ...]:
        written = set(touched(self.ctx.doc, doc))
        nums = numbers(doc, ex)
        rules = dict.fromkeys(link.rule for link in ex.links if link.anchor in written)
        return tuple(dict.fromkeys(rule_label(nums, r) for r in rules))

    # ---- changes that need no model

    async def dismiss(self, req: w.DismissRequest) -> w.Reply:
        entry = self._entry(req.key)
        if entry is None:
            return w.ErrorReply("That item is no longer open.")
        if entry.item.kind in ("clash", "conflict", "gave_up", "uncovered"):
            return w.ErrorReply("This can't be dismissed: the policy can't be trusted until it's fixed.")
        reason = req.reason.strip()
        if not reason:
            return w.ErrorReply("Say why, so the reason is kept with it.")
        d = Dismissal(entry.item.key, entry.fingerprint, reason)
        return await self._write(self._with_workspace(
            lambda ws: replace(ws, dismissed=(*(x for x in ws.dismissed if x.key != d.key), d))),
            w.Banner((f"Dismissed: {entry.item.title}",), (), ()))

    async def _policy_change(self, policy: Result[CheckedPolicy, object], banner: str) -> w.Reply:
        match policy:
            case Success(checked):
                files = replace(self.files, extraction=replace(self.files.extraction, policy=checked))
                return await self._write(files, w.Banner((banner,), (), ()))
            case Failure(errors):
                return w.ErrorReply(f"That change doesn't fit the policy: {errors}")
            case _:
                unreachable()

    async def _same(self, entry: Entry) -> w.Reply:
        a, b = entry.names
        variables = {v.name: v for v in self.ctx.policy.variables}
        keep, drop = (b, a) if not variables[a].description and variables[b].description else (a, b)
        match rename(self.files.extraction, drop, keep):
            case Success(ex):
                return await self._write(replace(self.files, extraction=ex),
                                         w.Banner((f"Merged: {entry.item.title}",), (), ()))
            case Failure(errors):
                return w.ErrorReply("They can't be merged: " + "; ".join(str(e) for e in errors))
            case _:
                unreachable()

    async def _different(self, entry: Entry, text: str) -> w.Reply:
        names = set(entry.names)
        p = self.ctx.policy

        def described(v: Variable) -> Variable:
            base = (v.description or name_words(v.name)).rstrip(".")
            return replace(v, description=f"{base} ({text.rstrip('.')})") if v.name in names else v
        policy = replace(p, variables=tuple(described(v) for v in p.variables))
        match check_policy(policy):
            case Success(checked):
                d = Dismissal(entry.item.key, entry.fingerprint, f"They differ: {text}")
                files = Files(self.files.text, replace(self.files.extraction, policy=checked), self.files.examples,
                              replace(self.files.workspace, dismissed=(*self.files.workspace.dismissed, d)))
                return await self._write(files, w.Banner((f"Told apart: {entry.item.title}",), (), ()))
            case Failure(errors):
                return w.ErrorReply("; ".join(str(e) for e in errors))
            case _:
                unreachable()

    async def _remove_name(self, entry: Entry) -> w.Reply:
        p = self.ctx.policy
        policy = replace(p, variables=tuple(v for v in p.variables if v.name not in entry.names))
        return await self._policy_change(check_policy(policy), f"Removed: {entry.item.title}")

    async def _add_sentence(self, entry: Entry) -> w.Reply:
        (rule,) = entry.rules
        sentence = self.sentences.get(rule)
        if sentence is None:
            return w.ErrorReply(NEEDS_MODEL.format("write this rule as a sentence"))
        doc = self.ctx.doc
        section = doc.sentences[-1].anchor.section if doc.sentences else "Rules"
        match apply(doc, (Insert(section, None, sentence),)):
            case Success(after):
                pass
            case Failure(message):
                return w.ErrorReply(message)
            case _:
                unreachable()
        anchors = touched(doc, after)
        ex = self.files.extraction
        links = (*ex.links, *(Link(rule, a) for a in anchors))
        files = replace(self.files, text=after.text, extraction=replace(ex, links=links))
        return await self._write(files, w.Banner((f"Added to the document: {sentence}",), (), ()))

    async def undo(self) -> w.Reply:
        previous = pop_undo(self.paths)
        if previous is None:
            return w.ErrorReply("There is nothing to undo.")
        return await self._write(previous, w.Banner(("Undid the last change.",), (), ()), undoable=False)

    # ---- extracting again

    async def extract_again(self) -> w.Reply:
        if self.ports.extractor is None:
            return w.ErrorReply(NEEDS_MODEL.format("extract again"))
        match load(self.paths):
            case Success(Files() as files):
                pass
            case Success(None):
                return w.ErrorReply("The policy file is missing.")
            case Failure(message):
                return w.ErrorReply(message)
            case _:
                unreachable()
        doc = parse(files.text)
        match await self.ports.extractor.extract(doc, vocabulary=files.extraction.policy):
            case Success(new):
                pass
            case Failure(e):
                return _error(e)
            case _:
                unreachable()
        snapshot = load_snapshot(self.paths)
        hand = {c.anchor for c in rule_changes(snapshot, files.extraction)} if snapshot is not None else set()
        diffs = rule_changes(files.extraction, new)

        def logic(rules: Sequence[Rule]) -> tuple[str, ...]:
            return tuple(pretty(rule_expr(r)) for r in rules)
        rid = f"r{next(self._ids)}"
        self.reextracts[rid] = _Reextract(files, new, tuple(d.anchor for d in diffs), self.version)
        return w.ReextractReply(w.ReextractView(rid, tuple(
            w.RuleDiff(d.anchor.text, d.anchor.section, logic(d.before), logic(d.after), d.anchor in hand,
                       "mine" if d.anchor in hand else "new") for d in diffs)))

    async def resolve(self, req: w.ResolveRequest) -> w.Reply:
        r = self.reextracts.get(req.reextract)
        if r is None:
            return w.ErrorReply("That extraction is no longer open.")
        if r.version != self.version:
            return w.ErrorReply("The policy changed since. Extract again.")
        if len(req.keep) != len(r.anchors):
            return w.ErrorReply("Choose a version for every sentence.")
        mine = tuple(a for a, k in zip(r.anchors, req.keep, strict=True) if k == "mine")
        current = r.files.extraction
        ids = {link.rule for link in current.links if link.anchor in mine}
        part = Extraction(CheckedPolicy(replace(current.policy, rules=tuple(x for x in current.policy.rules
                                                                            if x.id in ids))),
                          tuple(link for link in current.links if link.rule in ids), ())
        match merge(r.new, part, mine):
            case Success(merged):
                pass
            case Failure(errors):
                return w.ErrorReply("Your rules don't fit the new extraction: " + "; ".join(str(e) for e in errors))
            case _:
                unreachable()
        files = Files(r.files.text, merged, r.files.examples, replace(r.files.workspace, baseline=r.files.text))
        save_snapshot(self.paths, r.new)
        lost = broken(compile(merged.policy), files.examples)
        warning = tuple(f"Approved example {ex.id} no longer gets the answer you approved." for ex in lost)
        return await self._write(files, w.Banner(("Extracted again.",), warning, ()))


@dataclass
class Studio:
    """What the server holds: the folder it was started in, the ports, and the open document if there is one."""

    folder: Path
    ports: Ports
    session: Session | None = None
    message: str | None = None  # why the document given at start couldn't be opened
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def state(self) -> w.Reply:
        if self.session is not None:
            return self.session.view()
        return w.StartReply(str(self.folder), self.ports.model, self.message)

    async def start(self, req: w.StartRequest) -> w.Reply:
        if req.path:
            doc = (self.folder / req.path).resolve()
        elif req.name and req.text is not None:
            name = req.name.removesuffix(".md").strip()
            if not name or "/" in name or name.startswith("."):
                return w.ErrorReply("Give the document a simple file name.")
            doc = self.folder / f"{name}.md"
            if doc.exists():
                return w.ErrorReply(f"{doc.name} already exists; open it instead.")
            doc.write_text(req.text)
        else:
            return w.ErrorReply("Open a document or paste one.")
        if not doc.is_file():
            return w.ErrorReply(f"There is no document at {doc}.")
        match await Session.open(Paths.of(doc), self.ports):
            case Success(session):
                self.session, self.message = session, None
                return session.view()
            case Failure(message):
                self.message = message
                return w.ErrorReply(message)
            case _:
                unreachable()
