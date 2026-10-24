"""The document as the page shows it: sections, sentences numbered by the rules they hold, and tracked changes
against the baseline (the document as last extracted in full). Pure."""
from __future__ import annotations

import hashlib
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from difflib import SequenceMatcher

from policyproof.authoring.document import HEADING, Anchor, Document, gone, touched
from policyproof.authoring.extraction import Extraction
from policyproof.studio import wire as w
from policyproof.studio.workspace import Workspace

SIMILAR = 0.5  # a new sentence this close to a removed one in the same section is shown as a change to it


def sentence_id(a: Anchor) -> str:
    """Stable while the sentence's text and section stay the same, wherever it moves."""
    return "s" + hashlib.sha1(f"{a.section}\x00{a.text}\x00{a.n}".encode()).hexdigest()[:10]


def sentence_numbers(doc: Document, ex: Extraction) -> dict[Anchor, int]:
    """The sentences that hold rules, numbered 1, 2, ... in document order."""
    linked = {link.anchor for link in ex.links}
    ordered = [s.anchor for s in doc.sentences if s.anchor in linked]
    return {a: i for i, a in enumerate(ordered, 1)}


def numbers(doc: Document, ex: Extraction) -> dict[str, int]:
    """Each rule's number: the number of its first sentence in the document."""
    by_anchor = sentence_numbers(doc, ex)
    out: dict[str, int] = {}
    for link in ex.links:
        n = by_anchor.get(link.anchor)
        if n is not None and (link.rule not in out or n < out[link.rule]):
            out[link.rule] = n
    return out


def rule_label(nums: Mapping[str, int], rule: str) -> str:
    return f"Rule {nums[rule]}" if rule in nums else "A rule not in your document"


@dataclass(frozen=True, slots=True)
class Tracked:
    was: dict[Anchor, str]  # a changed sentence: its text in the baseline
    inserted: frozenset[Anchor]
    removed: tuple[Anchor, ...]  # baseline sentences with nothing in their place


def tracked(baseline: Document, now: Document) -> Tracked:
    added, dropped = touched(baseline, now), list(gone(baseline, now))
    was: dict[Anchor, str] = {}
    inserted: set[Anchor] = set()
    for a in added:
        scored = [(SequenceMatcher(None, b.text, a.text).ratio(), b) for b in dropped if b.section == a.section]
        best = max(scored, key=lambda t: t[0], default=None)
        if best is not None and best[0] >= SIMILAR:
            was[a] = best[1].text
            dropped.remove(best[1])
        else:
            inserted.add(a)
    return Tracked(was, frozenset(inserted), tuple(dropped))


def _levels(text: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for line in text.splitlines():
        m = HEADING.match(line)
        if m and m.group(2) not in out:
            out[m.group(2)] = len(m.group(1))
    return out


def doc_view(file: str, now: Document, baseline: Document, ex: Extraction, ws: Workspace,
             open_rules: Collection[str]) -> w.DocView:
    levels = _levels(now.text)
    nums = sentence_numbers(now, ex)
    t = tracked(baseline, now)
    rules_at: dict[Anchor, set[str]] = {}
    for link in ex.links:
        rules_at.setdefault(link.anchor, set()).add(link.rule)
    uncovered, background = set(ex.uncovered), set(ws.background)
    sections: dict[str, list[w.SentenceView]] = {"": []}
    sections.update((h, []) for h in levels)

    def state(a: Anchor) -> w.SentenceState:
        if rules_at.get(a, set()) & set(open_rules):
            return "open"
        if a in t.was:
            return "changed"
        if a in t.inserted:
            return "inserted"
        if a in uncovered:
            return "uncovered"
        return "background" if a in background else "plain"

    for s in now.sentences:
        a = s.anchor
        sections.setdefault(a.section, []).append(
            w.SentenceView(sentence_id(a), a.text, nums.get(a), state(a), t.was.get(a)))
    for a in t.removed:
        sections.setdefault(a.section, []).append(w.SentenceView(sentence_id(a), a.text, None, "removed", None))
    return w.DocView(file, tuple(w.SectionView(levels.get(h, 0), h, tuple(ss)) for h, ss in sections.items()
                                 if ss or h), len(ex.policy.rules))
