"""What the studio's page and server say to each other: plain data, the one definition both sides share. The JSON
Schema in `api.schema.json` is generated from these (`python -m policyproof.studio.schema`) and the page's TypeScript
types are generated from that, so a change here reaches both. Tagged unions carry a `kind`."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

type Tone = Literal["yes", "no", "none"]
type Level = Literal["error", "uncovered", "warning", "review"]
type ItemKind = Literal["clash", "conflict", "gap", "gave_up", "uncovered", "near_duplicate", "unused", "disjoint",
                        "impossible", "unreachable", "overlap", "inputs_related", "definition", "constraint",
                        "unlinked"]
type SentenceState = Literal["plain", "open", "changed", "inserted", "removed", "uncovered", "background"]


# ---- what an option does when the author picks it


@dataclass(frozen=True, slots=True)
class Choose:
    """This customer should get this outcome."""

    outcome: str
    kind: Literal["choose"] = "choose"


@dataclass(frozen=True, slots=True)
class Describe:
    """The author says it in a sentence ("It depends on…", "Something else…"); `prefix` goes before their text."""

    prompt: str
    prefix: str
    kind: Literal["describe"] = "describe"


@dataclass(frozen=True, slots=True)
class Dismiss:
    """Dismissed with this reason; None asks the author for one."""

    reason: str | None
    kind: Literal["dismiss"] = "dismiss"


@dataclass(frozen=True, slots=True)
class Background:
    kind: Literal["background"] = "background"


@dataclass(frozen=True, slots=True)
class Decides:
    """A sentence nothing came from does decide something: extract it again."""

    kind: Literal["decides"] = "decides"


@dataclass(frozen=True, slots=True)
class Same:
    """Two names are one thing: merge them."""

    kind: Literal["same"] = "same"


@dataclass(frozen=True, slots=True)
class Different:
    """Two names are different things: the author says how, and it goes into both descriptions."""

    prompt: str
    kind: Literal["different"] = "different"


@dataclass(frozen=True, slots=True)
class RemoveName:
    kind: Literal["remove_name"] = "remove_name"


@dataclass(frozen=True, slots=True)
class AddSentence:
    """Add a rule's sentence to the document."""

    kind: Literal["add_sentence"] = "add_sentence"


type Action = Choose | Describe | Dismiss | Background | Decides | Same | Different | RemoveName | AddSentence


@dataclass(frozen=True, slots=True)
class Option:
    label: str
    action: Action
    secondary: bool  # shown only once the author picks "Something else…"


# ---- the problems


@dataclass(frozen=True, slots=True)
class Verdict:
    """What one rule says for the customer, next to its sentence."""

    rule: str  # "Rule 4", or "A rule not in your document"
    sentence: str
    says: str
    tone: Tone


@dataclass(frozen=True, slots=True)
class Item:
    """One thing for the author to decide, in plain words."""

    key: str
    kind: ItemKind
    level: Level
    title: str
    facts: tuple[str, ...]
    lead: str | None
    verdicts: tuple[Verdict, ...]
    note: str | None
    question: str | None  # None: nothing to answer (the solver gave up)
    options: tuple[Option, ...]
    sentences: tuple[str, ...]  # ids of the document's sentences involved
    logic: tuple[str, ...]  # "Show the logic": the only place formulas appear
    new: bool  # caused by the last change
    dismissed_before: str | None  # the reason it was dismissed, when it came back because its rules changed


# ---- the document


@dataclass(frozen=True, slots=True)
class SentenceView:
    id: str
    text: str
    number: int | None  # the rule number: sentences with rules, counted in document order
    state: SentenceState
    was: str | None  # a changed sentence's text in the baseline document


@dataclass(frozen=True, slots=True)
class SectionView:
    level: int  # 0 before the first heading
    heading: str
    sentences: tuple[SentenceView, ...]


@dataclass(frozen=True, slots=True)
class DocView:
    file: str
    sections: tuple[SectionView, ...]
    rules: int


# ---- a proposal


@dataclass(frozen=True, slots=True)
class Change:
    kind: Literal["replace", "insert", "remove"]
    section: str
    before: str | None
    after: str | None


@dataclass(frozen=True, slots=True)
class Check:
    tone: Literal["ok", "open", "warn"]
    text: str


@dataclass(frozen=True, slots=True)
class Switch:
    """A new input the author can move between asking the customer and the business's systems."""

    var: str
    label: str
    role: Literal["ask", "system"]


@dataclass(frozen=True, slots=True)
class ProposalView:
    id: str
    changes: tuple[Change, ...]
    checks: tuple[Check, ...]
    additions: tuple[str, ...]  # new names in plain words: "The agent will now ask customers: …"
    switches: tuple[Switch, ...]
    risky: bool  # it causes a new problem or breaks an approved example
    attempts: int


# ---- the session


@dataclass(frozen=True, slots=True)
class ExampleView:
    id: str
    facts: tuple[str, ...]
    outcome: str


@dataclass(frozen=True, slots=True)
class Banner:
    """What the last change did."""

    fixed: tuple[str, ...]
    new: tuple[str, ...]
    changed: tuple[str, ...]  # "Rule 4", ...


@dataclass(frozen=True, slots=True)
class SessionView:
    file: str
    doc: DocView
    items: tuple[Item, ...]  # worst first
    groups: tuple[tuple[str, ...], ...]  # item keys decided together, when there is more than one
    open: int
    fixed: int
    examples: tuple[ExampleView, ...]
    banner: Banner | None
    can_undo: bool
    model: bool  # a model is configured, so proposals and extraction are available
    outside: bool  # the document changed on disk since the studio last read or wrote it
    done: bool
    version: int  # bumped on every change; a proposal made on an older version can't be accepted


@dataclass(frozen=True, slots=True)
class RuleDiff:
    """One sentence whose rules a new extraction reads differently."""

    sentence: str
    section: str
    mine: tuple[str, ...]  # the rules now, as logic (this view is for choosing between two readings)
    new: tuple[str, ...]
    hand_fixed: bool  # the author changed these rules since the last full extraction
    keep: Literal["mine", "new"]  # the default


@dataclass(frozen=True, slots=True)
class ReextractView:
    id: str
    diffs: tuple[RuleDiff, ...]


# ---- replies


@dataclass(frozen=True, slots=True)
class StateReply:
    state: SessionView
    kind: Literal["state"] = "state"


@dataclass(frozen=True, slots=True)
class ProposalReply:
    proposal: ProposalView
    kind: Literal["proposal"] = "proposal"


@dataclass(frozen=True, slots=True)
class ReextractReply:
    reextract: ReextractView
    kind: Literal["reextract"] = "reextract"


@dataclass(frozen=True, slots=True)
class OutsideReply:
    changed: bool
    kind: Literal["outside"] = "outside"


@dataclass(frozen=True, slots=True)
class StartReply:
    """No document yet: the page asks for one."""

    folder: str
    model: bool
    message: str | None  # why the document given at start couldn't be opened
    kind: Literal["start"] = "start"


@dataclass(frozen=True, slots=True)
class ErrorReply:
    message: str
    kind: Literal["error"] = "error"


type Reply = StateReply | ProposalReply | ReextractReply | OutsideReply | StartReply | ErrorReply


# ---- requests


@dataclass(frozen=True, slots=True)
class AnswerRequest:
    key: str
    option: int
    text: str  # what the author typed, for options that ask for a sentence; "" otherwise


@dataclass(frozen=True, slots=True)
class GroupAnswer:
    key: str
    option: int
    text: str


@dataclass(frozen=True, slots=True)
class GroupRequest:
    answers: tuple[GroupAnswer, ...]


@dataclass(frozen=True, slots=True)
class RewordRequest:
    proposal: str
    texts: tuple[str | None, ...]  # per change: the author's wording, or None to keep the proposed one


@dataclass(frozen=True, slots=True)
class AcceptRequest:
    proposal: str
    switch: tuple[str, ...]  # new inputs whose role the author switched


@dataclass(frozen=True, slots=True)
class DismissRequest:
    key: str
    reason: str


@dataclass(frozen=True, slots=True)
class ResolveRequest:
    reextract: str
    keep: tuple[Literal["mine", "new"], ...]  # per diff


@dataclass(frozen=True, slots=True)
class StartRequest:
    """Open a document by path, or save pasted text as NAME.md in the studio's folder."""

    path: str | None
    name: str | None
    text: str | None
