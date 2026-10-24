"""Merging a partial re-extraction into the policy, and the rule-by-rule changes a full one shows."""
from dataclasses import replace

from conftest import load
from returns.result import Failure

from policyproof.authoring.document import Anchor
from policyproof.authoring.merge import Additions, RuleChange, additions, merge, rename, rule_changes
from policyproof.authoring.ports import Extraction, Link
from policyproof.core.syntax import (
    And,
    BoolLit,
    BoolSort,
    CheckedPolicy,
    Cmp,
    EnumLit,
    Not,
    Outcome,
    System,
    Var,
    Variable,
    When,
)
from policyproof.core.typecheck import UnknownName

S4 = Anchor("Couriers", "Courier parcels are never refunded.")
S5 = Anchor("Couriers", "A late courier parcel is refunded if the customer asks.")
S6 = Anchor("Couriers", "Lost parcels are always refunded.")
S7 = Anchor("Damaged and sale items", "Damaged items are always replaced.")
S8 = Anchor("Damaged and sale items", "Sale items can't be returned or exchanged.")
LINKS = (Link("C4", S4), Link("C5", S5), Link("C6", S6), Link("C7", S7), Link("C8", S8))
COURIER = Cmp("eq", Var("carrier"), EnumLit("Carrier", "COURIER"))


def base() -> Extraction:
    return Extraction(load("defects/clashes.yaml"), LINKS, ())


def part(*rules, variables=(), outcomes=()) -> Extraction:
    p = base().policy
    policy = CheckedPolicy(replace(p, rules=tuple(rules), variables=p.variables + tuple(variables),
                                   outcomes=p.outcomes + tuple(outcomes)))
    return Extraction(policy, tuple(Link(r.id, a) for r, a in zip(rules, NEW_ANCHORS, strict=False)), ())


NEW = Anchor("Couriers", "Courier parcels are never refunded, unless they are lost.")
NEW_ANCHORS = (NEW, Anchor("Couriers", "Insured parcels get a voucher."))


def ids(ex: Extraction) -> tuple[str, ...]:
    return tuple(r.id for r in ex.policy.rules)


def test_merge_replaces_the_rules_of_a_changed_sentence():
    exception = When("x1", And((COURIER, Not(Var("lost")))), Not(Var("refund")))
    merged = merge(base(), part(exception), [S4]).unwrap()
    assert ids(merged) == ("C5", "C6", "C7", "C8", "C9", "R10")
    assert merged.policy.rules[-1] == replace(exception, id="R10")
    assert Link("R10", NEW) in merged.links and all(link.rule != "C4" for link in merged.links)
    assert len(merged.links) == len(LINKS)


def test_merge_adds_new_names_and_reports_them():
    insured = Variable("insured", BoolSort(), System(), "The parcel was insured.")
    voucher = Variable("voucher", BoolSort(), System(), "")
    rule = When("x1", Var("insured"), Var("voucher"))
    merged = merge(base(), part(rule, variables=(insured, voucher),
                                outcomes=(Outcome("voucher", (("voucher", BoolLit(True)),)),)), []).unwrap()
    assert additions(base().policy, merged.policy) == Additions(
        (insured, voucher), (), (Outcome("voucher", (("voucher", BoolLit(True)),)),))


def test_merge_rejects_an_ill_typed_part():
    result = merge(base(), part(When("x1", Var("refnd"), Var("refund"))), [S4])
    assert isinstance(result, Failure)
    assert any(isinstance(e, UnknownName) and e.name == "refnd" for e in result.failure())


def test_rename_merges_two_names():
    wants = Variable("wantsRefund", BoolSort(), System(), "The customer wants a refund.")
    ex = base()
    ex = replace(ex, policy=CheckedPolicy(replace(ex.policy, variables=(*ex.policy.variables, wants))))
    renamed = rename(ex, "asked", "wantsRefund").unwrap()
    names = [v.name for v in renamed.policy.variables]
    assert "asked" not in names and "wantsRefund" in names
    c5 = next(r for r in renamed.policy.rules if r.id == "C5")
    assert isinstance(c5, When) and isinstance(c5.when, And)
    assert Var("wantsRefund") in c5.when.args and Var("asked") not in c5.when.args


def test_rule_changes():
    old = base()
    p = old.policy
    c5 = next(r for r in p.rules if r.id == "C5")
    changed = replace(c5, when=And((COURIER, Var("asked"))))
    new_policy = CheckedPolicy(replace(p, rules=tuple(changed if r.id == "C5" else r for r in p.rules
                                                      if r.id != "C8")))
    new = Extraction(new_policy, tuple(link for link in LINKS if link.rule != "C8"), (S8,))
    assert [(rc.anchor, len(rc.before), len(rc.after)) for rc in rule_changes(old, new)] == [(S5, 1, 1), (S8, 1, 0)]
    assert rule_changes(old, old) == ()
    assert isinstance(rule_changes(old, new)[0], RuleChange)
