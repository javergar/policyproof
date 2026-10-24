"""A markdown policy as sentences with stable anchors, and the edits the studio makes to it.

A sentence is anchored by its section's heading, its own text (whitespace collapsed, list markers removed) and which
occurrence of that text in the section it is, so links survive edits elsewhere in the document. Offsets are worked out
on every parse and never stored.
"""
from __future__ import annotations

import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from difflib import SequenceMatcher
from itertools import pairwise
from typing import assert_never

from returns.result import Failure, Result, Success

HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
MARKER = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")
FENCE = re.compile(r"^\s*(```|~~~)")
SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"“(])")
EMPTY_ITEM = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s*$")
SIMILAR = 0.8


@dataclass(frozen=True, slots=True)
class Anchor:
    section: str  # the nearest heading's text above the sentence; "" before the first heading
    text: str  # the sentence, whitespace collapsed, list markers removed
    n: int = 0  # 0 for the first occurrence of this text in this section, then 1, 2, ...


@dataclass(frozen=True, slots=True)
class Sentence:
    anchor: Anchor
    start: int  # offsets into Document.text of the sentence's own characters
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
    after: Anchor | None  # None: a new paragraph at the end of the section
    text: str


@dataclass(frozen=True, slots=True)
class Remove:
    at: Anchor


type Edit = Replace | Insert | Remove


def _collapse(s: str) -> str:
    return " ".join(s.split())


def _blocks(text: str) -> list[tuple[str, int, int]]:
    """(section, start, end) of every paragraph's and list item's content, list markers excluded."""
    out: list[tuple[str, int, int]] = []
    section, fenced = "", False
    block: tuple[int, int] | None = None

    def close() -> None:
        if block is not None and block[1] > block[0]:
            out.append((section, *block))

    pos = 0
    for line in text.splitlines(keepends=True):
        start, body = pos, line.rstrip("\n")
        pos += len(line)
        if FENCE.match(body):
            fenced = not fenced
            close()
            block = None
            continue
        if fenced:
            continue
        heading = HEADING.match(body)
        if heading or not body.strip():
            close()
            block = None
            if heading:
                section = heading.group(2)
            continue
        marker = MARKER.match(body)
        if marker:
            close()
            block = (start + marker.end(), start + len(body))
        elif block is None:
            block = (start + len(body) - len(body.lstrip()), start + len(body))
        else:
            block = (block[0], start + len(body))
    close()
    return out


def parse(text: str) -> Document:
    sentences: list[Sentence] = []
    seen: Counter[tuple[str, str]] = Counter()
    for section, start, end in _blocks(text):
        raw = text[start:end]
        cuts = [0, *(m.end() for m in SPLIT.finditer(raw)), len(raw)]
        for a, b in pairwise(cuts):
            piece = raw[a:b]
            stripped = piece.strip()
            if not stripped:
                continue
            s = start + a + (len(piece) - len(piece.lstrip()))
            words = _collapse(stripped)
            sentences.append(Sentence(Anchor(section, words, seen[section, words]), s, s + len(stripped)))
            seen[section, words] += 1
    return Document(text, tuple(sentences))


def locate(doc: Document, a: Anchor) -> Sentence | None:
    """The exact sentence; else the most similar one in the same section, if similar enough."""
    for s in doc.sentences:
        if s.anchor == a:
            return s
    candidates = [(SequenceMatcher(None, s.anchor.text, a.text).ratio(), s) for s in doc.sentences
                  if s.anchor.section == a.section]
    best = max(candidates, key=lambda t: t[0], default=None)
    return best[1] if best is not None and best[0] >= SIMILAR else None


def _missing(a: Anchor) -> Failure[str]:
    where = f" in section {a.section!r}" if a.section else ""
    return Failure(f"can't find the sentence {a.text!r}{where}")


def _section_end(text: str, section: str) -> int | None:
    """Where a section's content ends: before the next heading, or at the end of the text."""
    pos, inside = 0, section == ""
    for line in text.splitlines(keepends=True):
        heading = HEADING.match(line.rstrip("\n"))
        if heading:
            if inside:
                return pos
            inside = heading.group(2) == section
        pos += len(line)
    return len(text) if inside else None


def _tidy(text: str) -> str:
    """Drop list items an edit emptied, and runs of blank lines."""
    lines = [line for line in text.splitlines(keepends=True) if not EMPTY_ITEM.match(line.rstrip("\n"))]
    return re.sub(r"\n{3,}", "\n\n", "".join(lines))


def _one(text: str, e: Edit) -> Result[str, str]:
    doc = parse(text)
    match e:
        case Replace(at, new):
            s = locate(doc, at)
            return _missing(at) if s is None else Success(text[:s.start] + new + text[s.end:])
        case Insert(section, after, new):
            if after is not None:
                s = locate(doc, after)
                return _missing(after) if s is None else Success(text[:s.end] + " " + new + text[s.end:])
            end = _section_end(text, section)
            if end is None:
                return Success(text.rstrip("\n") + f"\n\n## {section}\n\n{new}\n")
            head, tail = text[:end].rstrip("\n"), text[end:]
            return Success(head + f"\n\n{new}\n" + ("\n" + tail if tail else ""))
        case Remove(at):
            s = locate(doc, at)
            if s is None:
                return _missing(at)
            start, end = s.start, s.end
            if text[end:end + 1] == " ":
                end += 1
            elif start > 0 and text[start - 1] == " ":
                start -= 1
            return Success(_tidy(text[:start] + text[end:]))
        case _:
            assert_never(e)


def apply(doc: Document, edits: Sequence[Edit]) -> Result[Document, str]:
    """Edits apply in order, each to the document the previous one left; a sentence that can't be found fails."""
    text = doc.text
    for e in edits:
        match _one(text, e):
            case Success(changed):
                text = changed
            case Failure(message):
                return Failure(message)
    return Success(parse(text)) if edits else Success(doc)


def touched(before: Document, after: Document, edits: Sequence[Edit]) -> tuple[Anchor, ...]:
    """The anchors in `after` of every sentence an edit wrote, for partial re-extraction."""
    out: list[Anchor] = []
    for e in edits:
        match e:
            case Replace(at, new):
                section, written = at.section, new
            case Insert(section, _, new):
                written = new
            case Remove():
                continue
            case _:
                assert_never(e)
        texts = {s.anchor.text for s in parse(written).sentences}
        out += [s.anchor for s in after.sentences
                if s.anchor.section == section and s.anchor.text in texts and s.anchor not in out]
    return tuple(out)
