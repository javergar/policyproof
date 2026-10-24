"""Snapshots of the authoring prompts. After an intended change: PP_UPDATE_SNAPSHOTS=1 uv run pytest."""
import os
from pathlib import Path

from conftest import load

from policyproof.authoring.document import parse
from policyproof.authoring.llm.prompts import draft_prompt, extraction_prompt, sentence_prompt, title_prompt
from policyproof.authoring.ports import Choose, Describe, Situation

SNAPSHOT = Path(__file__).parent.parent / "snapshots" / "authoring_prompts.txt"
DELIVERY = (Path(__file__).parent.parent / "documents" / "delivery.md").read_text()


def prompts() -> list[str]:
    doc = parse(DELIVERY)
    couriers = tuple(s.anchor for s in doc.sentences if s.anchor.section == "Couriers")
    clashes = load("defects/clashes.yaml")
    situation = Situation(("Came by courier", "3 days late", "Asked for a refund"), couriers[:2],
                          (("refund", "A refund"), ("nothing", "Nothing")))
    return [extraction_prompt(doc, None, None, ""),
            extraction_prompt(doc, clashes, couriers[:1], "Lost parcels matter most."),
            draft_prompt(doc, situation, Choose("refund"), None),
            draft_prompt(doc, situation, Describe("only if more than 2 days late"), "Breaks approved example e1."),
            title_prompt(clashes, situation.customer),
            sentence_prompt(clashes, clashes.rules[1])]


def test_prompts_match_the_snapshot():
    text = "\n\n=====\n\n".join(prompts()) + "\n"
    if os.environ.get("PP_UPDATE_SNAPSHOTS"):
        SNAPSHOT.write_text(text)
    assert text == SNAPSHOT.read_text()


def test_the_prompt_numbers_every_sentence_under_its_heading():
    whole = prompts()[0]
    assert "## Couriers\n5. Courier parcels are never refunded." in whole
    assert "code is not policy" not in whole
