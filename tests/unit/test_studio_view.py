"""The document as the page shows it."""
from dataclasses import replace

from studio_fixtures import DOC, EXTRACTION, S4, S5, S6, S9, S10, TEXT

from policyproof.authoring.document import Anchor, Replace, apply, parse
from policyproof.studio.view import doc_view, numbers, sentence_id, tracked
from policyproof.studio.workspace import Workspace


def test_sentences_are_numbered_in_document_order():
    assert numbers(DOC, EXTRACTION) == {"C4": 1, "C5": 2, "C6": 3, "C10": 4, "C9": 5}


def test_a_replaced_sentence_is_tracked_against_its_old_text():
    now = apply(DOC, (Replace(S4, "Courier parcels are never refunded, unless lost."),)).unwrap()
    t = tracked(DOC, now)
    new = Anchor("Couriers", "Courier parcels are never refunded, unless lost.")
    assert t.was == {new: S4.text} and t.inserted == frozenset() and t.removed == ()


def test_an_unrelated_new_sentence_is_inserted_and_a_dropped_one_removed():
    now = parse(TEXT.replace("Lost parcels are always refunded.", "Weekend deliveries cost extra money today."))
    t = tracked(DOC, now)
    assert t.inserted == {Anchor("Couriers", "Weekend deliveries cost extra money today.")} and t.removed == (S6,)


def test_sentence_ids_are_stable_across_edits_elsewhere():
    now = apply(DOC, (Replace(S10, "Post parcels are never refunded."),)).unwrap()
    ids = {s.anchor: sentence_id(s.anchor) for s in now.sentences}
    assert ids[S4] == sentence_id(S4) and ids[S5] == sentence_id(S5)


def test_the_doc_view_marks_open_uncovered_and_background():
    ws = replace(Workspace.empty(TEXT), background=())
    view = doc_view("couriers.md", DOC, DOC, EXTRACTION, ws, {"C4"})
    assert [(s.level, s.heading) for s in view.sections] == [(1, "Couriers policy"), (2, "Couriers"), (2, "Post")]
    states = {s.text: (s.state, s.number) for sec in view.sections for s in sec.sentences}
    assert states[S4.text] == ("open", 1) and states[S5.text] == ("plain", 2)
    assert states["What courier customers get."] == ("uncovered", None)
    assert states[S9.text] == ("plain", 5) and view.rules == 5
    marked = doc_view("couriers.md", DOC, DOC, replace(EXTRACTION, uncovered=()),
                      replace(ws, background=(EXTRACTION.uncovered[0],)), ())
    assert marked.sections[0].sentences[0].state == "background"
