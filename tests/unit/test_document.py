"""Markdown policies as sentences with stable anchors, and the edits the studio makes to them."""
from pathlib import Path

from returns.result import Failure, Success

from policyproof.authoring.document import Anchor, Insert, Remove, Replace, apply, locate, parse, touched

DELIVERY = (Path(__file__).parent.parent / "documents" / "delivery.md").read_text()


def anchors(doc):
    return [s.anchor for s in doc.sentences]


def test_parse_finds_sections_and_sentences():
    doc = parse(DELIVERY)
    assert anchors(doc) == [
        Anchor("Delivery refunds policy", "What customers get when a parcel is late, lost or damaged."),
        Anchor("Late deliveries", "An express parcel more than 2 days late gets a refund if the customer asks."),
        Anchor("Late deliveries", "Express customers get a $10 voucher for any delay."),
        Anchor("Late deliveries", "A customer never gets both a refund and a voucher."),
        Anchor("Couriers", "Courier parcels are never refunded."),
        Anchor("Couriers", "A late courier parcel is refunded if the customer asks."),
        Anchor("Couriers", "Lost parcels are always refunded."),
        Anchor("Damaged and sale items", "Damaged items are always replaced."),
        Anchor("Damaged and sale items", "Sale items can't be returned or exchanged."),
        Anchor("Refund requests", "Refunds for late delivery are only given when the customer asks."),
    ]
    sale = doc.sentences[8]
    assert doc.text[sale.start:sale.end] == "Sale items can't be returned\nor exchanged."


def test_duplicate_sentences_get_distinct_anchors():
    doc = parse("# A\n\nKeep your receipt. Keep your receipt.\n\n# B\n\nKeep your receipt.\n")
    assert anchors(doc) == [Anchor("A", "Keep your receipt.", 0), Anchor("A", "Keep your receipt.", 1),
                            Anchor("B", "Keep your receipt.", 0)]
    changed = apply(doc, [Replace(Anchor("A", "Keep your receipt.", 1), "Bring it back.")]).unwrap()
    assert changed.text == "# A\n\nKeep your receipt. Bring it back.\n\n# B\n\nKeep your receipt.\n"


def test_insert_after_a_sentence():
    doc = parse(DELIVERY)
    after = Anchor("Couriers", "Courier parcels are never refunded.")
    changed = apply(doc, [Insert("Couriers", after, "Insured parcels are refunded.")]).unwrap()
    assert "- Courier parcels are never refunded. Insured parcels are refunded.\n" in changed.text
    assert Anchor("Couriers", "Insured parcels are refunded.") in anchors(changed)


def test_insert_at_the_end_of_a_section():
    changed = apply(parse(DELIVERY), [Insert("Couriers", None, "Insured parcels are refunded.")]).unwrap()
    assert "Lost parcels are always refunded.\n\nInsured parcels are refunded.\n\n## Damaged" in changed.text


def test_insert_into_a_new_section():
    changed = apply(parse(DELIVERY), [Insert("Insurance", None, "Insured parcels are refunded.")]).unwrap()
    assert changed.text.endswith("\n\n## Insurance\n\nInsured parcels are refunded.\n")


def test_remove_a_sentence():
    doc = parse(DELIVERY)
    changed = apply(doc, [Remove(Anchor("Couriers", "A late courier parcel is refunded if the customer asks."))])
    assert "- Lost parcels are always refunded.\n" in changed.unwrap().text


def test_removing_a_whole_list_item_drops_its_line():
    changed = apply(parse(DELIVERY), [Remove(Anchor("Couriers", "Courier parcels are never refunded."))]).unwrap()
    assert "## Couriers\n\n- A late courier parcel" in changed.text


def test_locate_survives_small_edits():
    doc = parse(DELIVERY.replace("Courier parcels are never refunded.", "Courier parcels are not refunded."))
    found = locate(doc, Anchor("Couriers", "Courier parcels are never refunded."))
    assert found is not None and found.anchor.text == "Courier parcels are not refunded."
    assert locate(doc, Anchor("Couriers", "Pets travel free on Tuesdays.")) is None


def test_a_missing_anchor_is_a_failure():
    result = apply(parse(DELIVERY), [Replace(Anchor("Nope", "x."), "y.")])
    assert isinstance(result, Failure) and "x." in result.failure()


def test_touched_names_the_new_sentences():
    doc = parse(DELIVERY)
    edits = [Replace(Anchor("Couriers", "Courier parcels are never refunded."),
                     "Courier parcels are never refunded, unless they are lost."),
             Insert("Couriers", None, "Insured parcels are refunded. Pets are not.")]
    after = apply(doc, edits).unwrap()
    assert touched(doc, after, edits) == (
        Anchor("Couriers", "Courier parcels are never refunded, unless they are lost."),
        Anchor("Couriers", "Insured parcels are refunded."), Anchor("Couriers", "Pets are not."))


def test_no_edits_is_the_identity():
    doc = parse(DELIVERY)
    assert apply(doc, []) == Success(doc)
