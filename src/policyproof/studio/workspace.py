"""The studio's files, in plain text next to the document so they can go in git:

```
NAME.md                the document; the studio edits it when a fix is accepted
NAME.policy.yaml       the policy
NAME.examples.yaml     approved example customers (`authoring.examples`)
.NAME.studio/          workspace.yaml: links from rules to sentences, sentences nothing came from, sentences marked
                       background, dismissed findings with their reasons, what was fixed, and the baseline document
                       that tracked changes are shown against; snapshot.yaml: the last full extraction, for
                       "Extract again"; undo/0001.yaml, ...: the four files as they were before each change
```

Links are anchors (section, sentence text, occurrence), re-found on load when the document was edited outside the
studio; offsets are never stored. Every write goes to a temporary file first, so a crash never leaves half a file.
"""
from __future__ import annotations

import hashlib
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import yaml
from returns.result import Failure, Result, Success

from policyproof.authoring.document import Anchor, Document, locate, parse
from policyproof.authoring.examples import Example, dumps, loads
from policyproof.authoring.extraction import Extraction, Link
from policyproof.core.codec import from_yaml, to_yaml
from policyproof.core.syntax import CheckedPolicy


@dataclass(frozen=True, slots=True)
class Paths:
    doc: Path
    policy: Path
    examples: Path
    folder: Path

    @staticmethod
    def of(doc: Path) -> Paths:
        stem = doc.name.removesuffix(".md")
        return Paths(doc, doc.with_name(f"{stem}.policy.yaml"), doc.with_name(f"{stem}.examples.yaml"),
                     doc.with_name(f".{stem}.studio"))

    @property
    def workspace(self) -> Path:
        return self.folder / "workspace.yaml"

    @property
    def snapshot(self) -> Path:
        return self.folder / "snapshot.yaml"

    @property
    def undo(self) -> Path:
        return self.folder / "undo"


@dataclass(frozen=True, slots=True)
class Dismissal:
    key: str  # which finding (studio.items)
    fingerprint: str  # of the rules and names it involved: when they change, the finding comes back
    reason: str


@dataclass(frozen=True, slots=True)
class Workspace:
    background: tuple[Anchor, ...]  # sentences the author marked as background information
    dismissed: tuple[Dismissal, ...]
    fixed: tuple[str, ...]  # titles of the problems fixed so far
    baseline: str  # the document as last extracted in full

    @staticmethod
    def empty(text: str) -> Workspace:
        return Workspace((), (), (), text)


@dataclass(frozen=True, slots=True)
class Files:
    text: str
    extraction: Extraction
    examples: tuple[Example, ...]
    workspace: Workspace


def digest(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(text)
    os.replace(tmp, path)


def _anchor(a: Anchor) -> dict[str, object]:
    return {"section": a.section, "text": a.text, "n": a.n}


def _dump(data: object) -> str:
    return yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=120)


def _workspace_text(f: Files) -> str:
    ws = f.workspace
    return _dump({
        "links": [{"rule": link.rule, **_anchor(link.anchor)} for link in f.extraction.links],
        "uncovered": [_anchor(a) for a in f.extraction.uncovered],
        "background": [_anchor(a) for a in ws.background],
        "dismissed": [{"key": d.key, "fingerprint": d.fingerprint, "reason": d.reason} for d in ws.dismissed],
        "fixed": list(ws.fixed),
        "baseline": ws.baseline,
    })


def _texts(f: Files) -> dict[str, str]:
    return {"document": f.text, "policy": to_yaml(f.extraction.policy), "examples": dumps(f.examples),
            "workspace": _workspace_text(f)}


def _refind(doc: Document, raw: object) -> Anchor | None:
    if not isinstance(raw, dict):
        return None
    a = Anchor(str(raw.get("section", "")), str(raw.get("text", "")), int(raw.get("n", 0)))
    s = locate(doc, a)
    return s.anchor if s is not None else None


def _anchors(doc: Document, raw: object) -> tuple[Anchor, ...]:
    found = (_refind(doc, x) for x in (raw if isinstance(raw, list) else []))
    return tuple(dict.fromkeys(a for a in found if a is not None))


def _policy(text: str) -> Result[CheckedPolicy, str]:
    return from_yaml(text).alt(lambda e: f"the policy: {e}")


def _from_texts(texts: Mapping[str, str | None]) -> Result[Files | None, str]:
    text, policy_text = texts.get("document"), texts.get("policy")
    if text is None:
        return Failure("the document doesn't exist")
    if policy_text is None:
        return Success(None)
    match _policy(policy_text):
        case Success(policy):
            pass
        case Failure(message):
            return Failure(message)
    examples: tuple[Example, ...] = ()
    if (examples_text := texts.get("examples")) is not None:
        match loads(policy, examples_text):
            case Success(examples):
                pass
            case Failure(message):
                return Failure(f"the examples: {message}")
    try:
        raw = yaml.safe_load(texts.get("workspace") or "") or {}
    except yaml.YAMLError as e:
        return Failure(f"the workspace: {e}")
    if not isinstance(raw, dict):
        return Failure("the workspace: expected a mapping")
    doc = parse(text)
    rules = {r.id for r in policy.rules}
    links: list[Link] = []
    for x in raw.get("links") or []:
        a = _refind(doc, x)
        if a is not None and isinstance(x, dict) and x.get("rule") in rules:
            links.append(Link(str(x["rule"]), a))
    dismissed = tuple(Dismissal(str(d["key"]), str(d["fingerprint"]), str(d["reason"]))
                      for d in raw.get("dismissed") or [] if isinstance(d, dict))
    ws = Workspace(_anchors(doc, raw.get("background")), dismissed, tuple(str(x) for x in raw.get("fixed") or []),
                   str(raw.get("baseline", text)))
    covered = {link.anchor for link in links}
    uncovered = tuple(a for a in _anchors(doc, raw.get("uncovered")) if a not in covered)
    return Success(Files(text, Extraction(policy, tuple(dict.fromkeys(links)), uncovered), examples, ws))


def _read(path: Path) -> str | None:
    return path.read_text() if path.exists() else None


def load(paths: Paths) -> Result[Files | None, str]:
    """The four files; None when there is no policy yet. A link whose sentence can't be re-found is dropped, so its
    rule shows as one that isn't in the document."""
    return _from_texts({"document": _read(paths.doc), "policy": _read(paths.policy),
                        "examples": _read(paths.examples), "workspace": _read(paths.workspace)})


def save(paths: Paths, f: Files) -> None:
    texts = _texts(f)
    _write(paths.doc, texts["document"])
    _write(paths.policy, texts["policy"])
    _write(paths.examples, texts["examples"])
    _write(paths.workspace, texts["workspace"])


def save_snapshot(paths: Paths, ex: Extraction) -> None:
    _write(paths.snapshot, _dump({"policy": to_yaml(ex.policy),
                                  "links": [{"rule": link.rule, **_anchor(link.anchor)} for link in ex.links],
                                  "uncovered": [_anchor(a) for a in ex.uncovered]}))


def load_snapshot(paths: Paths) -> Extraction | None:
    """The last full extraction, as it was: its anchors are those of the document it was extracted from."""
    if not paths.snapshot.exists():
        return None
    raw = yaml.safe_load(paths.snapshot.read_text())
    policy = _policy(raw["policy"]).value_or(None)
    if policy is None:
        return None

    def anchor(x: dict[str, object]) -> Anchor:
        return Anchor(str(x["section"]), str(x["text"]), int(str(x["n"])))
    return Extraction(policy, tuple(Link(str(x["rule"]), anchor(x)) for x in raw["links"]),
                      tuple(anchor(x) for x in raw["uncovered"]))


def _undo_files(paths: Paths) -> list[Path]:
    return sorted(paths.undo.glob("*.yaml")) if paths.undo.exists() else []


def can_undo(paths: Paths) -> bool:
    return bool(_undo_files(paths))


def push_undo(paths: Paths, f: Files) -> None:
    existing = _undo_files(paths)
    n = int(existing[-1].stem) + 1 if existing else 1
    _write(paths.undo / f"{n:04d}.yaml", _dump(_texts(f)))


def pop_undo(paths: Paths) -> Files | None:
    """The files as they were before the last change, removed from the history; None when there is none."""
    existing = _undo_files(paths)
    if not existing:
        return None
    last = existing[-1]
    texts = yaml.safe_load(last.read_text())
    last.unlink()
    return _from_texts(texts).value_or(None)
