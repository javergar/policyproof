"""The studio's files: the document, the policy, the examples and the workspace folder beside them."""
from conftest import load as policy_file
from returns.result import Success

from policyproof.authoring.document import Anchor, parse
from policyproof.authoring.examples import Example
from policyproof.authoring.extraction import Extraction, Link
from policyproof.core.syntax import BoolLit, EnumLit, IntLit
from policyproof.studio.workspace import (
    Dismissal,
    Files,
    Paths,
    Workspace,
    can_undo,
    digest,
    load,
    load_snapshot,
    pop_undo,
    push_undo,
    save,
    save_snapshot,
)

TEXT = ("## Couriers\n\n- Courier parcels are never refunded.\n"
        "- A late courier parcel is refunded if the customer asks. Lost parcels are always refunded.\n\n"
        "## Post\n\nPost parcels that aren't lost are not refunded.\n")
DOC = parse(TEXT)
S4, S5, S6, S10 = (s.anchor for s in DOC.sentences)
POLICY = policy_file("defects/couriers.yaml")
EXTRACTION = Extraction(POLICY, (Link("C4", S4), Link("C5", S5), Link("C6", S6), Link("C10", S10)), ())
EXAMPLE = Example("post-lost", (("asked", BoolLit(False)), ("carrier", EnumLit("Carrier", "POST")),
                                ("daysLate", IntLit(0)), ("lost", BoolLit(True))), "refund")


def files(text: str = TEXT) -> Files:
    ws = Workspace((), (Dismissal("unused:x", "abc", "kept for later"),), ("Late courier parcel",), text)
    return Files(text, EXTRACTION, (EXAMPLE,), ws)


def paths(tmp_path) -> Paths:
    p = Paths.of(tmp_path / "couriers.md")
    p.doc.write_text(TEXT)
    return p


def test_paths_sit_next_to_the_document(tmp_path):
    p = Paths.of(tmp_path / "delivery-refunds.md")
    assert p.policy.name == "delivery-refunds.policy.yaml" and p.examples.name == "delivery-refunds.examples.yaml"
    assert p.folder.name == ".delivery-refunds.studio" and p.folder.parent == tmp_path


def test_files_round_trip(tmp_path):
    p = paths(tmp_path)
    save(p, files())
    assert load(p) == Success(files())


def test_a_missing_policy_loads_as_none(tmp_path):
    assert load(paths(tmp_path)) == Success(None)


def test_a_missing_document_is_an_error(tmp_path):
    assert not isinstance(load(Paths.of(tmp_path / "nothing.md")), Success)


def test_links_are_refound_after_an_outside_edit(tmp_path):
    p = paths(tmp_path)
    save(p, files())
    edited = TEXT.replace("Courier parcels are never refunded.", "Courier parcels are never ever refunded.")
    p.doc.write_text(edited)
    got = load(p).unwrap()
    assert got is not None
    assert Link("C4", Anchor("Couriers", "Courier parcels are never ever refunded.")) in got.extraction.links


def test_a_link_that_cant_be_refound_is_dropped(tmp_path):
    p = paths(tmp_path)
    save(p, files())
    p.doc.write_text(TEXT.replace("Courier parcels are never refunded.", "Something else entirely, about weather."))
    got = load(p).unwrap()
    assert got is not None and {link.rule for link in got.extraction.links} == {"C5", "C6", "C10"}


def test_undo_survives_a_restart(tmp_path):
    p = paths(tmp_path)
    first, second = files(), files(TEXT + "\nOne more sentence.\n")
    assert not can_undo(p)
    push_undo(p, first)
    push_undo(p, second)
    assert can_undo(p)
    assert pop_undo(Paths.of(p.doc)) == second
    assert pop_undo(Paths.of(p.doc)) == first
    assert pop_undo(p) is None and not can_undo(p)


def test_snapshot_round_trip(tmp_path):
    p = paths(tmp_path)
    assert load_snapshot(p) is None
    save_snapshot(p, EXTRACTION)
    assert load_snapshot(p) == EXTRACTION


def test_digest_is_of_the_text():
    assert digest("a") == digest("a") != digest("b")
