"""Deciding: the first outcome the facts prove, or the one question that settles it.

0. Facts must name known, non-derived variables with values of the right sort, or the result is `InvalidFacts`.
1. The rules and the firm facts must be consistent, or the result is a `Contradiction` naming the rules and facts.
   Firm facts: anything from a system; answers to a question about an askable variable; and volunteered facts about
   askable variables that don't need confirmation. Customers can't supply system facts: what they say about one is
   never firm.
2. The first outcome (in policy order) proven from the firm facts is `Decided`. A later outcome is never decided past
   one that might hold: an earlier outcome that more facts could still prove means asking (step 4), and one the
   solver gives up on means `Escalate`. An earlier outcome no facts could ever prove (the policy never settles it)
   doesn't block.
3. If an outcome is proven only with a volunteered fact, that fact is confirmed first: `NeedInfo(reason="confirm")`.
4. Otherwise the policy asks about the askable variable whose answers decide the most outcomes (the what-if table),
   ties broken by policy order; Int and Real questions (whose answers can't be enumerated) only when nothing else
   is left. While an earlier outcome is open, only a question linked to it through the rules whose answer settles
   it, alone or together with one more answer (`JOINT_ANSWERS`), is asked, those that settle it alone first; when
   none can (it hangs on system facts not given, say), or after `JOINT_TRIES` combinations, the result is
   `Escalate`. With nothing left to ask, or no
   outcomes at all: `Escalate`.
"""
from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from itertools import combinations, product
from typing import Literal, assert_never

from returns.pipeline import is_successful

from policyproof.core.facts import Answered, Fact, Facts, FromSystem, Volunteered, all_facts
from policyproof.core.prove import Contingent, Inconsistent, Proven, Refuted, Undetermined, classify
from policyproof.core.semantics import free_vars, rule_expr
from policyproof.core.solver import Compiled, FactLabel, Label, RuleLabel, Sat, Unknown, Unsat, check, decidable, fact
from policyproof.core.syntax import (
    And,
    Ask,
    BoolLit,
    BoolSort,
    Cmp,
    Derived,
    EnumLit,
    EnumSort,
    Expr,
    Lit,
    Outcome,
    System,
    Var,
    Variable,
)
from policyproof.core.typecheck import signature, sort_name, sort_of

type Reason = Literal["missing", "confirm", "unclear"]


@dataclass(frozen=True, slots=True)
class Decided:
    outcome: str
    rules: tuple[str, ...]
    facts_used: tuple[Fact, ...]


@dataclass(frozen=True, slots=True)
class NeedInfo:
    var: str
    question: str
    reason: Reason
    what_if: tuple[tuple[Lit, str | None], ...]  # each possible answer, and the outcome it would prove


@dataclass(frozen=True, slots=True)
class Contradiction:
    rules: tuple[str, ...]
    facts: tuple[Fact, ...]


@dataclass(frozen=True, slots=True)
class Escalate:
    reason: str


@dataclass(frozen=True, slots=True)
class InvalidFacts:
    """Facts that don't fit the policy: unknown or derived variables, or values of the wrong sort."""

    errors: tuple[str, ...]


type Decision = Decided | NeedInfo | Contradiction | Escalate | InvalidFacts


def outcome_expr(o: Outcome) -> Expr:
    parts = tuple(Cmp("eq", Var(v), lit) for v, lit in o.assignment)
    return parts[0] if len(parts) == 1 else And(parts)


def fact_assertions(fs: Iterable[Fact]) -> list[tuple[Label, Expr]]:
    """One tracked `var == value` per distinct fact."""
    return list(dict.fromkeys(fact(f.var, f.value) for f in fs))


def _rule_ids(c: Compiled, core: frozenset[Label]) -> tuple[str, ...]:
    return tuple(r.id for r in c.policy.rules if RuleLabel(r.id) in core)


def _facts_in(core: frozenset[Label], fs: Sequence[Fact]) -> tuple[Fact, ...]:
    return tuple(f for f in fs if FactLabel(f.var, f.value) in core)


def _variable(c: Compiled, name: str) -> Variable:
    return next(v for v in c.policy.variables if v.name == name)


def _needs_confirmation(c: Compiled, f: Fact) -> bool:
    role = _variable(c, f.var).role
    return isinstance(f.provenance, Volunteered) and isinstance(role, Ask) and role.confirm_volunteered


def _is_firm(c: Compiled, f: Fact) -> bool:
    role = _variable(c, f.var).role
    match f.provenance:
        case FromSystem():
            return True
        case Answered():
            return isinstance(role, Ask)
        case Volunteered():
            return isinstance(role, Ask) and not role.confirm_volunteered
        case _:
            assert_never(f.provenance)


def fact_errors(c: Compiled, fs: Facts) -> tuple[str, ...]:
    sig = signature(c.policy)
    found: list[str] = []
    for f in all_facts(fs):
        if f.var not in sig.variables:
            found.append(f"unknown variable {f.var!r}")
        elif isinstance(_variable(c, f.var).role, Derived):
            found.append(f"{f.var} is derived by the rules; it can't be given as a fact")
        else:
            got = sort_of(sig, f.value, f.var)
            if not is_successful(got):
                found.append(f"{f.var}: {got.failure()}")
            elif got.unwrap() != sig.variables[f.var]:
                found.append(f"{f.var} is {sort_name(sig.variables[f.var])}, not {sort_name(got.unwrap())}")
    return tuple(found)


@dataclass(frozen=True, slots=True)
class _Hit:
    outcome: Outcome
    core: frozenset[Label]


@dataclass(frozen=True, slots=True)
class _GaveUp:
    outcome: str
    reason: str


@dataclass(frozen=True, slots=True)
class _Open:
    """An outcome the facts leave open that more facts could still prove: no later outcome is decided past it."""
    outcome: str


def _inputs(c: Compiled) -> frozenset[str]:
    return frozenset(v.name for v in c.policy.variables if not isinstance(v.role, Derived))


def _step(c: Compiled, o: Outcome, given: Sequence[tuple[Label, Expr]]
          ) -> Proven | Inconsistent | _GaveUp | _Open | None:
    """Where the facts leave one outcome: proven, contradictory facts, given up on, open, or (None) out of the way of
    later outcomes, because the facts rule it out or no further facts could ever prove it."""
    verdict = classify(c, outcome_expr(o), given)
    match verdict:
        case Proven() | Inconsistent():
            return verdict
        case Refuted():
            return None
        case Undetermined(reason):
            return _GaveUp(o.name, reason)
        case Contingent():
            match decidable(c, _inputs(c), given=[e for _, e in given], outcomes=[o.name]):
                case Sat():
                    return _Open(o.name)
                case Unknown(reason):
                    return _GaveUp(o.name, reason)
                case Unsat():
                    return None
                case other:
                    assert_never(other)
        case _:
            assert_never(verdict)


def _first_proven(c: Compiled, fs: Sequence[Fact]) -> _Hit | _GaveUp | _Open | None:
    """The first outcome the facts prove, unless an earlier one is still open or the solver gave up on it."""
    given = fact_assertions(fs)
    for o in c.policy.outcomes:
        match _step(c, o, given):
            case Proven(core):
                return _Hit(o, core)
            case _GaveUp() | _Open() as stop:
                return stop
            case Inconsistent() | None:
                pass
    return None


def _answers(v: Variable) -> tuple[Lit, ...]:
    match v.sort:
        case BoolSort():
            return (BoolLit(True), BoolLit(False))
        case EnumSort(name, values):
            return tuple(EnumLit(name, x) for x in values)
        case _:
            return ()  # Int and Real answers can't be enumerated


def what_if(c: Compiled, firm: Sequence[Fact], var: str) -> tuple[tuple[Lit, str | None], ...]:
    out: list[tuple[Lit, str | None]] = []
    for value in _answers(_variable(c, var)):
        hit = _first_proven(c, [*firm, Fact(var, value, Answered("", ""))])
        out.append((value, hit.outcome.name if isinstance(hit, _Hit) else None))
    return tuple(out)


JOINT_ANSWERS = 2  # how many answers together may settle an open outcome before decide stops looking and escalates
JOINT_TRIES = 256  # how many combinations of answers decide tries for an open outcome before it stops looking


def _linked(c: Compiled, o: Outcome) -> frozenset[str]:
    """The variables linked to the outcome's through rules that share variables: only these can bear on it."""
    near = {v for v, _ in o.assignment}
    groups = [free_vars(rule_expr(r)) for r in c.policy.rules]
    while grown := [g for g in groups if g & near and not g <= near]:
        near.update(*grown)
    return frozenset(near)


def _settling(c: Compiled, firm: Sequence[Fact], candidates: Sequence[Variable], o: Outcome) -> list[Variable] | None:
    """The candidates whose possible answers, alone or with up to `JOINT_ANSWERS - 1` others, prove the open outcome
    `o` or move it out of the way; questions that settle it alone come first. None means decide stopped looking after
    `JOINT_TRIES` combinations of answers."""
    tries = 0
    for k in range(1, JOINT_ANSWERS + 1):
        found: set[str] = set()
        for group in combinations(candidates, k):
            for values in product(*(_answers(v) for v in group)):
                if (tries := tries + 1) > JOINT_TRIES:
                    return None
                answered = [*firm, *(Fact(v.name, x, Answered("", "")) for v, x in zip(group, values, strict=True))]
                if isinstance(_step(c, o, fact_assertions(answered)), Proven | None):
                    found.update(v.name for v in group)
                    break
        if found:
            return [v for v in candidates if v.name in found]
    return []


def _question(c: Compiled, firm: Sequence[Fact], every: Sequence[Fact], unclear: frozenset[str],
              blocked: str | None) -> Decision:
    """`blocked`: an outcome still open that holds up the decision, so only a question that can settle it is asked."""
    known = {f.var for f in firm}
    used = frozenset().union(*(free_vars(rule_expr(r)) for r in c.policy.rules))
    candidates = [v for v in c.policy.variables
                  if isinstance(v.role, Ask) and v.name not in known and v.name in used]
    enumerable = [v for v in candidates if _answers(v)]
    if blocked is not None:
        held = next(o for o in c.policy.outcomes if o.name == blocked)
        near = _linked(c, held)
        settling = _settling(c, firm, [v for v in enumerable if v.name in near], held)
        if settling is None:
            return Escalate(f"outcome {blocked} may still hold, and decide stopped looking for questions that settle "
                            f"it after {JOINT_TRIES} combinations of answers")
        candidates = settling or [v for v in candidates if not _answers(v) and v.name in near]
        if not candidates:
            missing = [v.name for v in c.policy.variables
                       if isinstance(v.role, System) and v.name not in known and v.name in near]
            unsupplied = f"; it depends on facts not given: {', '.join(missing)}" if missing else ""
            return Escalate(f"outcome {blocked} may still hold and no answers to the questions left (up to "
                            f"{JOINT_ANSWERS} together) can settle it{unsupplied}")
    else:
        candidates = enumerable or candidates
    if not candidates:
        return Escalate("no outcome can be proven and there is nothing left to ask")
    tables = [what_if(c, firm, v.name) for v in candidates]
    scores = [sum(o is not None for _, o in t) for t in tables]
    best = max(range(len(candidates)), key=lambda i: (scores[i], -i))
    v, role = candidates[best], candidates[best].role
    assert isinstance(role, Ask)
    reason: Reason = ("unclear" if v.name in unclear
                      else "confirm" if any(f.var == v.name for f in every) else "missing")
    return NeedInfo(v.name, role.question, reason, tables[best])


def firm_facts(c: Compiled, fs: Facts) -> tuple[Fact, ...]:
    """The facts a decision may rest on (see the module docstring). Assumes `fact_errors` found nothing."""
    return tuple(f for f in all_facts(fs) if _is_firm(c, f))


def decide(c: Compiled, fs: Facts, *, unclear: frozenset[str] = frozenset()) -> Decision:
    """`unclear`: variables whose last answer couldn't be read, so the question is asked again."""
    invalid = fact_errors(c, fs)
    if invalid:
        return InvalidFacts(invalid)
    if not c.policy.outcomes:
        return Escalate("the policy has no outcomes")
    every, firm = all_facts(fs), firm_facts(c, fs)
    match check(c, fact_assertions(firm)):
        case Unsat(core):
            return Contradiction(_rule_ids(c, core), _facts_in(core, firm))
        case Unknown(reason):
            return Escalate(f"the solver gave up: {reason}")
        case Sat():
            pass
        case other:
            assert_never(other)
    blocked: str | None = None
    match _first_proven(c, firm):
        case _Hit(o, core):
            return Decided(o.name, _rule_ids(c, core), _facts_in(core, firm))
        case _GaveUp(name, reason):
            return Escalate(f"the solver gave up on outcome {name}: {reason}")
        case _Open(name):
            blocked = name
        case None:
            pass
    pending = [f for f in every if _needs_confirmation(c, f)]
    hit = _first_proven(c, [*firm, *pending]) if pending else None
    if isinstance(hit, _Hit):
        used = [f for f in _facts_in(hit.core, every) if _needs_confirmation(c, f)]
        if used:
            var = used[0].var
            role = _variable(c, var).role
            assert isinstance(role, Ask)
            return NeedInfo(var, role.question, "confirm", what_if(c, firm, var))
    return _question(c, firm, every, unclear, blocked)
