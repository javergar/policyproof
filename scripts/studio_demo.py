"""Try the studio without a model: the couriers policy, with scripted stand-ins for the drafter and the extractor.

    uv run python scripts/studio_demo.py [--folder DIR] [--port N] [--no-browser]

It writes `couriers.md`, its policy and workspace into DIR (a new temporary folder by default) and serves them. The
stand-ins know one rewrite: courier parcels get exceptions for the customers the author says should get a refund.
Every check is real: Z3 judges each proposal exactly as with a model.
"""
from __future__ import annotations

import argparse
import re
import sys
import tempfile
import webbrowser
from dataclasses import dataclass, replace
from pathlib import Path

import uvicorn
from returns.result import Failure, Result, Success

from policyproof.authoring.document import Anchor, Document, Edit, Replace, parse
from policyproof.authoring.extraction import Extraction, Link
from policyproof.authoring.ports import Answer, Choose, Describe, Situation
from policyproof.core.codec import from_yaml
from policyproof.core.syntax import And, CheckedPolicy, Cmp, EnumLit, Expr, IntLit, Not, Rule, Var, When
from policyproof.effects.errors import LLMError, Unavailable
from policyproof.studio.cli import HOST, _free_port
from policyproof.studio.server import app
from policyproof.studio.session import Ports, Studio
from policyproof.studio.workspace import Files, Paths, Workspace, save, save_snapshot

TEXT = """# Couriers policy

What customers get when a courier or post parcel goes wrong.

## Couriers

- Courier parcels are never refunded.
- A late courier parcel is refunded if the customer asks. Lost parcels are always refunded.

## Post

Post parcels that aren't lost are not refunded. Days late are never negative.
"""

POLICY = """
policy: couriers
version: "1"
sorts:
  Carrier: [POST, COURIER]
variables:
  carrier:
    sort: Carrier
    role: system
    description: Who delivered the parcel.
    display: { COURIER: "Came by courier", POST: "Came by post" }
  daysLate:
    sort: Int
    role: system
    description: Days after the promised date.
    display: "Days late: {}"
  asked:
    sort: Bool
    role: ask
    question: "Would you like a refund?"
    description: The customer asked for a refund.
    display: { true: "Asked for a refund", false: "Didn't ask for a refund" }
  lost:
    sort: Bool
    role: system
    description: The parcel was lost.
    display: { true: "The parcel was lost", false: "The parcel arrived" }
  refund: { sort: Bool, role: derived, description: The customer gets a refund. }
rules:
  - { id: C4, when: { eq: [carrier, COURIER] }, then: { not: refund } }
  - { id: C5, when: { and: [{ eq: [carrier, COURIER] }, { gt: [daysLate, 0] }, asked] }, then: refund }
  - { id: C6, when: lost, then: refund }
  - { id: C10, when: { and: [{ eq: [carrier, POST] }, { not: lost }] }, then: { not: refund } }
  - { id: C9, constraint: { ge: [daysLate, 0] } }
outcomes:
  refund: { refund: true, display: "A refund" }
  nothing: { refund: false, display: "No refund" }
"""

COURIER = Cmp("eq", Var("carrier"), EnumLit("Carrier", "COURIER"))
LATE_ASKED = And((Cmp("gt", Var("daysLate"), IntLit(0)), Var("asked")))
BASE = "Courier parcels are never refunded"
EXCEPTIONS = {"they arrive late and the customer asks": LATE_ASKED, "they are lost": Var("lost")}


def _courier_sentence(doc: Document) -> Anchor | None:
    return next((s.anchor for s in doc.sentences if s.anchor.text.startswith(BASE)), None)


def _exceptions(text: str) -> list[str]:
    return [e for e in EXCEPTIONS if e in text]


def _rule_for(text: str, rid: str) -> Rule | None:
    if not text.startswith(BASE):
        return None
    unless: list[Expr] = [Not(EXCEPTIONS[e]) for e in _exceptions(text)]
    return When(rid, And((COURIER, *unless)) if unless else COURIER, Not(Var("refund")))


@dataclass
class DemoDrafter:
    """Adds the exceptions the author's answer needs to the courier sentence."""

    async def draft(self, doc: Document, situation: Situation, answer: Answer,
                    failure: str | None) -> Result[tuple[Edit, ...], LLMError]:
        at = _courier_sentence(doc)
        if at is None:
            return Success(())
        wanted = set(_exceptions(at.text))
        refund = isinstance(answer, Choose) and answer.outcome == "refund"
        said = answer.text.lower() if isinstance(answer, Describe) else ""
        facts = " ".join(situation.customer).lower()
        if refund or "should get a refund" in said:
            if "asked for a refund" in facts and "didn't ask" not in facts:
                wanted.add("they arrive late and the customer asks")
            if "was lost" in facts:
                wanted.add("they are lost")
        if "lost" in said and "a refund" in said:
            wanted.add("they are lost")
        order = [e for e in EXCEPTIONS if e in wanted]
        text = BASE + (", unless " + ", or ".join(order) if order else "") + "."
        return Success((Replace(at, text),))


@dataclass
class DemoExtractor:
    """Reads courier sentences into rules; anything else is left uncovered."""

    async def extract(self, doc: Document, *, vocabulary: CheckedPolicy | None = None,
                      only: tuple[Anchor, ...] | None = None, guidance: str = "") -> Result[Extraction, LLMError]:
        assert vocabulary is not None, "the demo extracts only parts of the couriers document"
        rules: list[Rule] = []
        links: list[Link] = []
        uncovered: list[Anchor] = []
        for n, a in enumerate(only or (), 1):
            rule = _rule_for(re.sub(r"\s+", " ", a.text), f"x{n}")
            if rule is None:
                uncovered.append(a)
            else:
                rules.append(rule)
                links.append(Link(rule.id, a))
        return Success(Extraction(CheckedPolicy(replace(vocabulary, rules=tuple(rules))), tuple(links),
                                  tuple(uncovered)))


@dataclass
class NoPhraser:
    """Titles fall back to the facts in words."""

    async def title(self, p: CheckedPolicy, customer: tuple[str, ...]) -> Result[str, LLMError]:
        return Failure(Unavailable("demo"))

    async def sentence(self, p: CheckedPolicy, rule: Rule) -> Result[str, LLMError]:
        return Failure(Unavailable("demo"))


def write(folder: Path) -> Path:
    doc_path = folder / "couriers.md"
    doc_path.write_text(TEXT)
    doc = parse(TEXT)
    intro, s4, s5, s6, s10, s9 = (s.anchor for s in doc.sentences)
    policy = from_yaml(POLICY).unwrap()
    ex = Extraction(policy, (Link("C4", s4), Link("C5", s5), Link("C6", s6), Link("C10", s10), Link("C9", s9)),
                    (intro,))
    paths = Paths.of(doc_path)
    save(paths, Files(TEXT, ex, (), Workspace.empty(TEXT)))
    save_snapshot(paths, ex)
    return doc_path


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="studio_demo.py")
    p.add_argument("--folder", type=Path)
    p.add_argument("--port", type=int, default=0)
    p.add_argument("--no-browser", action="store_true")
    args = p.parse_args(argv)
    folder = args.folder or Path(tempfile.mkdtemp(prefix="policyproof-studio-"))
    folder.mkdir(parents=True, exist_ok=True)
    doc = write(folder)
    token, port = "demo", args.port or _free_port()
    studio = Studio(folder, Ports(DemoExtractor(), DemoDrafter(), NoPhraser()))
    url = f"http://{HOST}:{port}/?t={token}"
    print(f"studio demo on {doc}\n{url}", flush=True)
    if not args.no_browser:
        webbrowser.open(url)
    uvicorn.Server(uvicorn.Config(app(studio, token, open_doc=doc), host=HOST, port=port, log_level="warning")).run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
