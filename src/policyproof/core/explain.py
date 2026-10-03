"""Explanations of a decision: the facts and where they came from, the rule steps, and a runnable SMT-LIB proof."""
from __future__ import annotations

from dataclasses import dataclass
from typing import assert_never

from policyproof.core.decide import Contradiction, Decided, Decision, Escalate, NeedInfo, outcome_expr
from policyproof.core.facts import Fact, Facts, all_facts
from policyproof.core.render import pretty, smt_declarations, to_smtlib
from policyproof.core.semantics import rule_expr
from policyproof.core.solver import Compiled
from policyproof.core.syntax import Cmp, Constraint, Define, Expr, Not, Rule, Var, When
from policyproof.core.typecheck import signature


@dataclass(frozen=True, slots=True)
class Step:
    rule: str
    premise: str
    conclusion: str
    explain: str | None


@dataclass(frozen=True, slots=True)
class Trace:
    facts: tuple[Fact, ...]
    steps: tuple[Step, ...]
    smtlib: str  # run it with any SMT solver: `unsat` means the outcome is proven
    expected: str  # "unsat", "sat", or "" when there is nothing to run


def step(r: Rule) -> Step:
    match r:
        case When(rid, when, then, _, explain):
            return Step(rid, pretty(when), pretty(then), explain)
        case Define(rid, var, as_, _, explain):
            return Step(rid, pretty(as_), f"{var} (and only then)", explain)
        case Constraint(rid, expr, _, explain):
            return Step(rid, "", pretty(expr), explain)
        case _:
            assert_never(r)


def script(c: Compiled, rule_ids: tuple[str, ...], fs: tuple[Fact, ...], goal: Expr | None) -> str:
    """SMT-LIB: the declarations, the named rules, the facts, and `goal` negated; then `(check-sat)`."""
    lines = [smt_declarations(signature(c.policy))]
    lines += [f"(assert (! {to_smtlib(rule_expr(r))} :named |{r.id}|))" for r in c.policy.rules if r.id in rule_ids]
    lines += [f"(assert {to_smtlib(Cmp('eq', Var(f.var), f.value))})" for f in dict.fromkeys(fs)]
    if goal is not None:
        lines.append(f"(assert {to_smtlib(Not(goal))})")
    return "\n".join([*lines, "(check-sat)"])


def explain(c: Compiled, d: Decision, fs: Facts) -> Trace:
    every = all_facts(fs)
    all_ids = tuple(r.id for r in c.policy.rules)
    match d:
        case Decided(outcome, rules, used):
            goal = outcome_expr(next(o for o in c.policy.outcomes if o.name == outcome))
            steps = tuple(step(r) for r in c.policy.rules if r.id in rules)
            return Trace(used, steps, script(c, rules, used, goal), "unsat")
        case NeedInfo():
            return Trace(every, (), script(c, all_ids, every, None), "sat")
        case Contradiction(rules, facts):
            steps = tuple(step(r) for r in c.policy.rules if r.id in rules)
            return Trace(facts, steps, script(c, rules, facts, None), "unsat")
        case Escalate():
            return Trace(every, (), "", "")
        case _:
            assert_never(d)
