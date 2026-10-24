"""Merging a partial re-extraction into the policy, renaming, and the rule-by-rule changes of a full re-extraction."""
from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import assert_never

from returns.result import Result

from policyproof.authoring.document import Anchor
from policyproof.authoring.extraction import Extraction, Link
from policyproof.core.semantics import rule_expr
from policyproof.core.syntax import (
    And,
    Arith,
    BoolLit,
    CheckedPolicy,
    Cmp,
    Constraint,
    Define,
    EnumLit,
    Expr,
    Iff,
    Implies,
    In,
    IntLit,
    Not,
    Or,
    Outcome,
    Policy,
    RealLit,
    Rule,
    Var,
    Variable,
    When,
)
from policyproof.core.typecheck import SortError, check_policy

RULE_NUMBER = re.compile(r"(\d+)\Z")


@dataclass(frozen=True, slots=True)
class Additions:
    variables: tuple[Variable, ...]
    values: tuple[tuple[str, str], ...]  # (sort, new value) on existing sorts
    outcomes: tuple[Outcome, ...]


@dataclass(frozen=True, slots=True)
class RuleChange:
    anchor: Anchor
    before: tuple[Rule, ...]
    after: tuple[Rule, ...]


def _by_name[T](base: Sequence[T], part: Sequence[T], name: str) -> tuple[T, ...]:
    """`base` in its order with `part`'s version of each name, then `part`'s new names."""
    newer = {getattr(x, name): x for x in part}
    known = {getattr(x, name) for x in base}
    return (*(newer.get(getattr(x, name), x) for x in base), *(x for x in part if getattr(x, name) not in known))


def _fresh_ids(taken: Sequence[str], count: int) -> list[str]:
    numbers = [int(m.group(1)) for rid in taken if (m := RULE_NUMBER.search(rid))]
    start = max(numbers, default=len(taken)) + 1
    return [f"R{start + i}" for i in range(count)]


def merge(base: Extraction, part: Extraction, replaced: Sequence[Anchor]) -> Result[Extraction, tuple[SortError, ...]]:
    """Drop the rules linked only to `replaced` sentences, add `part`'s rules under fresh ids, and take `part`'s
    sorts, variables and outcomes where they extend or update `base`'s. The result is typechecked."""
    gone = set(replaced)
    kept_links = tuple(link for link in base.links if link.anchor not in gone)
    linked = {link.rule for link in kept_links}
    all_linked = {link.rule for link in base.links}
    kept_rules = tuple(r for r in base.policy.rules if r.id in linked or r.id not in all_linked)
    fresh = dict(zip((r.id for r in part.policy.rules),
                     _fresh_ids([r.id for r in base.policy.rules], len(part.policy.rules)), strict=True))
    new_rules = tuple(replace(r, id=fresh[r.id]) for r in part.policy.rules)
    new_links = tuple(Link(fresh[link.rule], link.anchor) for link in part.links if link.rule in fresh)
    links = kept_links + new_links
    covered = {link.anchor for link in links}
    candidates = (*base.uncovered, *part.uncovered)
    uncovered = tuple(dict.fromkeys(a for a in candidates if a not in gone and a not in covered))
    p, q = base.policy, part.policy
    policy = Policy(p.name, p.version, _by_name(p.sorts, q.sorts, "name"), _by_name(p.variables, q.variables, "name"),
                    kept_rules + new_rules, _by_name(p.outcomes, q.outcomes, "name"))
    return check_policy(policy).map(lambda checked: Extraction(checked, links, uncovered))


def additions(before: CheckedPolicy, after: CheckedPolicy) -> Additions:
    old_vars, old_outcomes = {v.name for v in before.variables}, {o.name for o in before.outcomes}
    old_values = {s.name: set(s.values) for s in before.sorts}
    return Additions(tuple(v for v in after.variables if v.name not in old_vars),
                     tuple((s.name, x) for s in after.sorts if s.name in old_values
                           for x in s.values if x not in old_values[s.name]),
                     tuple(o for o in after.outcomes if o.name not in old_outcomes))


def _rename(e: Expr, old: str, new: str) -> Expr:
    match e:
        case Var(name):
            return Var(new) if name == old else e
        case BoolLit() | IntLit() | RealLit() | EnumLit():
            return e
        case Not(arg):
            return Not(_rename(arg, old, new))
        case And(args):
            return And(tuple(_rename(a, old, new) for a in args))
        case Or(args):
            return Or(tuple(_rename(a, old, new) for a in args))
        case Implies(lhs, rhs):
            return Implies(_rename(lhs, old, new), _rename(rhs, old, new))
        case Iff(lhs, rhs):
            return Iff(_rename(lhs, old, new), _rename(rhs, old, new))
        case Cmp(op, lhs, rhs):
            return Cmp(op, _rename(lhs, old, new), _rename(rhs, old, new))
        case Arith(op, args):
            return Arith(op, tuple(_rename(a, old, new) for a in args))
        case In(arg, values):
            return In(_rename(arg, old, new), values)
        case _:
            assert_never(e)


def _rename_rule(r: Rule, old: str, new: str) -> Rule:
    match r:
        case When(_, when, then):
            return replace(r, when=_rename(when, old, new), then=_rename(then, old, new))
        case Define(_, var, as_):
            return replace(r, var=new if var == old else var, as_=_rename(as_, old, new))
        case Constraint(_, expr):
            return replace(r, expr=_rename(expr, old, new))
        case _:
            assert_never(r)


def rename(ex: Extraction, old: str, new: str) -> Result[Extraction, tuple[SortError, ...]]:
    """Merge two names for one thing: every use of `old` becomes `new`, and `old` is dropped."""
    p = ex.policy
    outcomes = tuple(replace(o, assignment=tuple((new if v == old else v, x) for v, x in o.assignment))
                     for o in p.outcomes)
    policy = replace(p, variables=tuple(v for v in p.variables if v.name != old),
                     rules=tuple(_rename_rule(r, old, new) for r in p.rules), outcomes=outcomes)
    return check_policy(policy).map(lambda checked: replace(ex, policy=checked))


def _rules_at(ex: Extraction, a: Anchor) -> tuple[Rule, ...]:
    ids = {link.rule for link in ex.links if link.anchor == a}
    return tuple(r for r in ex.policy.rules if r.id in ids)


def _shape(rules: Sequence[Rule]) -> list[str]:
    return sorted(repr((type(r).__name__, rule_expr(r))) for r in rules)


def rule_changes(old: Extraction, new: Extraction) -> tuple[RuleChange, ...]:
    """Per sentence, the rules that differ between two extractions (ids ignored); sentences on one side count."""
    anchors = dict.fromkeys(link.anchor for link in (*old.links, *new.links))
    out: list[RuleChange] = []
    for a in anchors:
        before, after = _rules_at(old, a), _rules_at(new, a)
        if _shape(before) != _shape(after):
            out.append(RuleChange(a, before, after))
    return tuple(out)
