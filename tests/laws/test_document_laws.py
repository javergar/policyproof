"""D1 to D3: parsing is stable, a replacement changes exactly one sentence, and no edits change nothing."""
from collections import Counter

from hypothesis import given
from hypothesis import strategies as st

from policyproof.authoring.document import Replace, apply, parse

SENTENCES = st.sampled_from(["Late parcels get a refund.", "Couriers never refund.", "Keep your receipt.",
                             "Sale items can't be returned.", "Lost parcels are refunded!", "Is it insured?"])
PARAGRAPH = st.lists(SENTENCES, min_size=1, max_size=3).map(" ".join)
ITEM = st.tuples(st.sampled_from(["- ", "* ", "1. "]), PARAGRAPH).map("".join)
BLOCK = PARAGRAPH | st.lists(ITEM, min_size=1, max_size=3).map("\n".join)
SECTION = st.tuples(st.sampled_from(["Late", "Couriers", "Sales"]), st.lists(BLOCK, min_size=1, max_size=3)).map(
    lambda t: f"## {t[0]}\n\n" + "\n\n".join(t[1]) + "\n")
DOCS = st.lists(SECTION, min_size=1, max_size=3).map("\n".join)


@given(DOCS)
def test_d1_parsing_its_own_text_gives_the_same_document(text):
    doc = parse(text)
    assert parse(doc.text) == doc


@given(DOCS, st.data())
def test_d2_a_replacement_changes_exactly_one_sentence(text, data):
    doc = parse(text)
    target = data.draw(st.sampled_from(doc.sentences)).anchor
    new = "Insured parcels are always refunded."
    after = apply(doc, [Replace(target, new)]).unwrap()
    before_texts = Counter((s.anchor.section, s.anchor.text) for s in doc.sentences)
    after_texts = Counter((s.anchor.section, s.anchor.text) for s in after.sentences)
    before_texts[target.section, target.text] -= 1
    before_texts[target.section, new] += 1
    assert +before_texts == +after_texts


@given(DOCS)
def test_d3_no_edits_change_nothing(text):
    doc = parse(text)
    assert apply(doc, []).unwrap() == doc
