"""LLMDrafter against a scripted model: its edits become document edits with the right anchors."""
import asyncio

from scripted_model import Script

from policyproof.authoring.document import Anchor, Insert, Remove, Replace, apply, parse
from policyproof.authoring.llm.drafter import LLMDrafter
from policyproof.authoring.ports import Choose, Describe, Situation

DOC = parse("# A\n\nKeep your receipt. Keep your receipt.\n\n## Couriers\n\nCourier parcels are never refunded.\n")
SITUATION = Situation(("Came by courier", "3 days late"), (Anchor("Couriers", "Courier parcels are never refunded."),),
                      (("refund", "A refund"), ("nothing", "Nothing")))


REFUND = Choose("refund")


def draft(script, answer=REFUND, failure=None):
    return asyncio.run(LLMDrafter(script.model).draft(DOC, SITUATION, answer, failure))


def test_drafts_map_to_edits():
    s = Script({"edits": [
        {"kind": "replace", "section": "Couriers", "sentence": "Courier parcels are never refunded.",
         "text": "Courier parcels are never refunded, unless they arrive late."},
        {"kind": "insert", "section": "Couriers", "sentence": None, "text": "Lost parcels are refunded."},
        {"kind": "replace", "section": "A", "sentence": "Keep your receipt.", "text": "Keep it."},
        {"kind": "remove", "section": "A", "sentence": "Keep your receipt.", "text": None}]})
    assert draft(s).unwrap() == (
        Replace(Anchor("Couriers", "Courier parcels are never refunded."),
                "Courier parcels are never refunded, unless they arrive late."),
        Insert("Couriers", None, "Lost parcels are refunded."),
        Replace(Anchor("A", "Keep your receipt.", 0), "Keep it."),
        Remove(Anchor("A", "Keep your receipt.", 0)))
    # edits apply one after another: once the first copy is replaced, the other is the first one left
    assert apply(DOC, draft(s).unwrap()).unwrap().text.startswith("# A\n\nKeep it.\n\n## Couriers")


def test_the_situation_and_answer_reach_the_prompt():
    s = Script({"edits": []})
    draft(s, answer=Describe("only if more than 2 days late"))
    text = s.instructions()
    assert "Came by courier" in text and "Courier parcels are never refunded." in text
    assert "only if more than 2 days late" in text and "A refund" in text


def test_failure_reaches_the_prompt():
    s = Script({"edits": []})
    draft(s, failure="Breaks approved example post-lost.")
    assert "Breaks approved example post-lost." in s.instructions()


def test_an_edit_without_text_is_sent_back():
    s = Script({"edits": [{"kind": "replace", "section": "Couriers", "sentence": "Courier parcels are never refunded.",
                           "text": None}]}, {"edits": []})
    assert draft(s).unwrap() == ()
    assert any("text" in p for p in s.retry_prompts())
