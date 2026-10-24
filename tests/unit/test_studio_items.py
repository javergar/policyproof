"""Every problem and finding as an item in the same style: a situation in plain words, one question, answers."""
import re
from dataclasses import replace

import pytest
from conftest import load
from returns.result import Success
from studio_fixtures import DOC, EXTRACTION, TEXT

from policyproof.authoring.document import parse
from policyproof.authoring.extraction import Extraction
from policyproof.core.codec import from_yaml
from policyproof.core.problems import Clash, GaveUp, Problems
from policyproof.studio import wire as w
from policyproof.studio.items import Context, items
from policyproof.studio.workspace import Dismissal, Workspace

WS = Workspace.empty(TEXT)


def listing(extraction=EXTRACTION, doc=DOC, ws=WS, **kw):
    return items(Context.of(extraction, doc, ws, **kw))


def by_kind(lst, kind):
    return [e.item for e in lst.entries if e.item.kind == kind]


def bare(name):
    """A policy with no document: every rule is one not in the document."""
    return Extraction(load(name), (), ())


INLINE = """
policy: inline
version: "1"
variables:
  daysLate: { sort: Int, role: system, description: Days late. }
  express: { sort: Bool, role: system, description: Sent express. }
  late: { sort: Bool, role: derived, description: The parcel is late. }
  refund: { sort: Bool, role: derived, description: The customer gets a refund. }
rules:
  - { id: D1, define: { var: late, as: { gt: [daysLate, 0] } } }
  - { id: D2, when: express, then: { gt: [daysLate, 1] } }
  - { id: D3, when: late, then: refund }
outcomes:
  refund: { refund: true }
  nothing: { refund: false }
"""


def test_a_clash_is_an_example_customer_with_verdicts():
    late = next(i for i in by_kind(listing(), "clash") if i.key == "clash:C4+C5")
    assert late.level == "error" and late.question == "What should this customer get?"
    assert "Who delivered the parcel: COURIER" in late.facts
    assert late.lead == "Two rules give opposite answers for this customer:" and late.note is None
    assert [(v.rule, v.sentence, v.says, v.tone) for v in late.verdicts] == [
        ("Rule 1", "Courier parcels are never refunded.", "Nothing", "no"),
        ("Rule 2", "A late courier parcel is refunded if the customer asks.", "Refund", "yes")]
    labels = [(o.label, o.secondary) for o in late.options]
    assert labels == [("Refund", False), ("Nothing", False), ("Something else…", False),
                      ("It depends on something else…", False)]
    assert late.options[0].action == w.Choose("refund")
    assert all(line.startswith(("Rule", "Z3")) for line in late.logic)


def test_a_three_rule_clash_blames_no_pair():
    policy = load("defects/not_total.yaml")
    clash = by_kind(listing(Extraction(policy, (), ()), parse(""), Workspace.empty("")), "clash")[0]
    assert clash.lead == "These 3 rules can't all be followed for this customer:"
    assert clash.note is not None and "no single rule is wrong" in clash.note
    assert [v.rule for v in clash.verdicts] == ["A rule not in your document"] * 3


def test_a_gap_offers_every_outcome_and_a_person():
    gap = by_kind(listing(bare("defects/gap.yaml"), parse(""), Workspace.empty("")), "gap")[0]
    assert gap.title == "Nothing in the policy says what happens to this customer"
    assert gap.facts == ("The parcel arrived late: no",)
    assert [o.label for o in gap.options] == ["Refund", "Something else…", "A person should decide this one"]
    assert gap.options[-1].action == w.Dismiss("A person decides cases like this")


@pytest.mark.parametrize(("source", "kinds"), [
    ("defects/clashes.yaml", {"clash", "gap", "disjoint", "overlap", "constraint", "unlinked"}),
    ("defects/near_duplicate.yaml", {"near_duplicate", "gap", "disjoint"}),
    ("defects/unreachable_outcome.yaml", {"unreachable", "constraint"}),
    ("defects/bare_assertion.yaml", {"impossible"}),
    ("defects/conflict.yaml", {"conflict", "unused"}),
    (INLINE, {"definition", "inputs_related"}),
])
def test_every_finding_kind_becomes_an_item(source, kinds):
    policy = from_yaml(INLINE).unwrap() if source == INLINE else load(source)
    lst = listing(Extraction(policy, (), ()), parse(""), Workspace.empty(""))
    got = {e.item.kind for e in lst.entries}
    assert kinds <= got, got
    for e in lst.entries:
        assert e.item.title and e.item.question and e.item.options, e.item


def test_a_check_that_gave_up_is_an_error_with_nothing_to_answer():
    ctx = Context.of(EXTRACTION, DOC, WS)
    lst = items(replace(ctx, problems=Problems((GaveUp("clashes", "timeout"),), False)))
    gave_up = by_kind(lst, "gave_up")[0]
    assert gave_up.title == "This part of the policy is too complex to check"
    assert gave_up.level == "error" and gave_up.question is None and gave_up.options == ()


NAMES = re.compile(r"\b(daysLate|isFinalSale|finalSale|itemCategory|outsideControl|coolingOff|wantsRefund)\b")


@pytest.mark.parametrize("source", ["defects/clashes.yaml", "defects/near_duplicate.yaml", "defects/not_total.yaml",
                                    "defects/bare_assertion.yaml", "defects/conflict.yaml", INLINE])
def test_no_formula_or_name_outside_the_logic(source):
    policy = from_yaml(INLINE).unwrap() if source == INLINE else load(source)
    for e in listing(Extraction(policy, (), ()), parse(""), Workspace.empty("")).entries:
        i = e.item
        texts = [i.title, *i.facts, i.lead or "", i.note or "", i.question or "",
                 *(x for v in i.verdicts for x in (v.rule, v.sentence, v.says)),
                 *(o.label for o in i.options)]
        for text in texts:
            assert not NAMES.search(text) and not re.search(r"→|¬|∧|unsat|witness", text), (i.kind, text)


def test_items_are_ordered_errors_first():
    kinds = [e.item.kind for e in listing().entries]
    assert kinds == ["clash", "clash", "uncovered", "constraint"]


def test_problems_that_share_rules_are_grouped():
    assert [set(g) for g in listing().groups] == [{"clash:C4+C5", "clash:C4+C6"}]


def test_background_sentences_are_not_items():
    ws = replace(WS, background=EXTRACTION.uncovered)
    assert "uncovered" not in {e.item.kind for e in listing(ws=ws).entries}


def test_a_dismissal_lapses_when_its_rules_change():
    constraint = by_kind(listing(), "constraint")[0]
    entry = next(e for e in listing().entries if e.item.key == constraint.key)
    ws = replace(WS, dismissed=(Dismissal(constraint.key, entry.fingerprint, "Exactly right"),))
    assert "constraint" not in {e.item.kind for e in listing(ws=ws).entries}
    changed = from_yaml(TEXT_POLICY_WITH_C9_CHANGED).unwrap()
    back = by_kind(listing(replace(EXTRACTION, policy=changed), ws=ws), "constraint")[0]
    assert back.dismissed_before == "Exactly right"


def test_errors_cant_be_dismissed():
    clash = by_kind(listing(), "clash")[0]
    entry = next(e for e in listing().entries if e.item.key == clash.key)
    ws = replace(WS, dismissed=(Dismissal(clash.key, entry.fingerprint, "no"),))
    assert clash.key in {e.item.key for e in listing(ws=ws).entries}


def test_new_items_are_marked():
    lst = items(Context.of(EXTRACTION, DOC, WS), new_keys=frozenset({"clash:C4+C6"}))
    assert {e.item.key: e.item.new for e in lst.entries if e.item.kind == "clash"} == {
        "clash:C4+C5": False, "clash:C4+C6": True}


def test_model_titles_replace_the_fact_phrases():
    late = next(f for f in Context.of(EXTRACTION, DOC, WS).problems.found
                if isinstance(f, Clash) and f.rules == ("C4", "C5"))
    lst = listing(titles={late.customer: "A late courier parcel"})
    assert next(i for i in by_kind(lst, "clash") if i.key == "clash:C4+C5").title == "A late courier parcel"


TEXT_POLICY_WITH_C9_CHANGED = (
    (__import__("pathlib").Path(__file__).parents[1] / "policies/defects/couriers.yaml").read_text()
    .replace("{ id: C9, constraint: { ge: [daysLate, 0] } }", "{ id: C9, constraint: { ge: [daysLate, 1] } }"))
assert isinstance(from_yaml(TEXT_POLICY_WITH_C9_CHANGED), Success)
