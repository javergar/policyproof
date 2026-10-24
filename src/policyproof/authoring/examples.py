"""Approved example customers: the answers an author has signed off, checked again after every change.

An example's facts must be complete enough that `decide` returns `Decided(outcome)`: the facts prove the answer, not
merely allow it. The file sits next to the policy:

```yaml
examples:
  - id: late-courier-asked
    customer: { carrier: COURIER, daysLate: 3, asked: true }
    outcome: refund
```
"""
from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import assert_never

import yaml
from returns.result import Failure, Result, Success

from policyproof.core.decide import Decided, decide
from policyproof.core.facts import Answered, Fact, Facts, FromSystem, facts
from policyproof.core.problems import Customer
from policyproof.core.solver import Compiled
from policyproof.core.syntax import Ask, BoolLit, CheckedPolicy, Derived, EnumLit, IntLit, Lit, RealLit, System
from policyproof.guards.values import literal_for

ID = re.compile(r"[A-Za-z0-9_-]+\Z")


@dataclass(frozen=True, slots=True)
class Example:
    id: str
    customer: Customer  # complete enough to decide
    outcome: str


def to_facts(p: CheckedPolicy, ex: Example) -> Facts:
    roles = {v.name: v.role for v in p.variables}
    fs: list[Fact] = []
    for var, value in ex.customer:
        match roles[var]:
            case System():
                fs.append(Fact(var, value, FromSystem("example")))
            case Ask(question):
                fs.append(Fact(var, value, Answered(question, "example")))
            case Derived():
                raise ValueError(f"example {ex.id}: {var} is derived and can't be given")
            case other:
                assert_never(other)
    return facts(*fs)


def holds(c: Compiled, ex: Example) -> bool:
    """The example's facts still prove its outcome. An example that names a variable the policy no longer has as an
    input doesn't hold."""
    inputs = {v.name for v in c.policy.variables if not isinstance(v.role, Derived)}
    if any(var not in inputs for var, _ in ex.customer):
        return False
    d = decide(c, to_facts(c.policy, ex))
    return isinstance(d, Decided) and d.outcome == ex.outcome


def broken(c: Compiled, examples: Sequence[Example]) -> tuple[Example, ...]:
    return tuple(ex for ex in examples if not holds(c, ex))


def _example(p: CheckedPolicy, i: int, item: object, seen: set[str]) -> Result[Example, str]:
    where = f"examples[{i}]"
    if not isinstance(item, dict) or set(item) != {"id", "customer", "outcome"}:
        return Failure(f"{where}: give exactly id, customer and outcome")
    ex_id, customer, outcome = item["id"], item["customer"], item["outcome"]
    if not isinstance(ex_id, str) or not ID.match(ex_id):
        return Failure(f"{where}.id: use letters, digits, - and _ only")
    if ex_id in seen:
        return Failure(f"example {ex_id}: the id is used twice")
    seen.add(ex_id)
    if not isinstance(customer, dict) or not customer:
        return Failure(f"example {ex_id}: customer must map variables to values")
    variables = {v.name: v for v in p.variables}
    pairs: list[tuple[str, Lit]] = []
    for var, value in customer.items():
        v = variables.get(var)
        if v is None:
            return Failure(f"example {ex_id}: customer.{var}: the policy has no variable {var!r}")
        if isinstance(v.role, Derived):
            return Failure(f"example {ex_id}: customer.{var}: {var} is decided by the rules and can't be given")
        match literal_for(p, var, value):
            case Success(lit):
                pairs.append((var, lit))
            case Failure(message):
                return Failure(f"example {ex_id}: customer.{var}: {message}")
    if outcome not in {o.name for o in p.outcomes}:
        return Failure(f"example {ex_id}: outcome: the policy has no outcome {outcome!r}")
    return Success(Example(ex_id, tuple(sorted(pairs)), outcome))


def loads(p: CheckedPolicy, text: str) -> Result[tuple[Example, ...], str]:
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as e:
        return Failure(f"invalid YAML: {e}")
    items = data.get("examples") if isinstance(data, dict) else None
    if not isinstance(items, list):
        return Failure("the file needs a list under examples")
    seen: set[str] = set()
    out: list[Example] = []
    for i, item in enumerate(items):
        match _example(p, i, item, seen):
            case Success(ex):
                out.append(ex)
            case Failure(message):
                return Failure(message)
    return Success(tuple(out))


def _plain(lit: Lit) -> object:
    match lit:
        case BoolLit(b):
            return b
        case IntLit(n):
            return n
        case RealLit(q):
            return {"real": str(q)}
        case EnumLit(_, value):
            return value
        case _:
            assert_never(lit)


def dumps(examples: Sequence[Example]) -> str:
    data = {"examples": [{"id": ex.id, "customer": {var: _plain(x) for var, x in ex.customer}, "outcome": ex.outcome}
                         for ex in examples]}
    return yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=120)
