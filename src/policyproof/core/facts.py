"""Facts with provenance, and how facts from different sources combine.

A system of record beats the customer's answer to a question, which beats something the customer only mentioned in
passing. `merge` keeps, for each variable, every fact at the highest rank seen. Conflicting facts at the same rank
are both kept, so a contradiction stays visible to `decide` instead of being resolved silently. `merge` is a
semilattice join: associative, commutative and idempotent (law L9).
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from functools import reduce
from typing import assert_never

from policyproof.core.syntax import Lit


@dataclass(frozen=True, slots=True)
class FromSystem:
    source: str


@dataclass(frozen=True, slots=True)
class Answered:
    question: str
    quote: str


@dataclass(frozen=True, slots=True)
class Volunteered:
    quote: str


type Provenance = FromSystem | Answered | Volunteered


@dataclass(frozen=True, slots=True)
class Fact:
    var: str
    value: Lit
    provenance: Provenance


type Facts = Mapping[str, frozenset[Fact]]


def rank(p: Provenance) -> int:
    match p:
        case FromSystem():
            return 3
        case Answered():
            return 2
        case Volunteered():
            return 1
        case _:
            assert_never(p)


def merge(a: Facts, b: Facts) -> Facts:
    out: dict[str, frozenset[Fact]] = {}
    for var in a.keys() | b.keys():
        both = a.get(var, frozenset()) | b.get(var, frozenset())
        top = max(rank(f.provenance) for f in both)
        out[var] = frozenset(f for f in both if rank(f.provenance) == top)
    return out


def facts(*fs: Fact) -> Facts:
    """Facts from individual statements, merged."""
    return reduce(merge, ({f.var: frozenset({f})} for f in fs), {})


def all_facts(fs: Facts) -> tuple[Fact, ...]:
    """Every fact, in a stable order (by variable name, then value and provenance)."""
    return tuple(sorted((f for group in fs.values() for f in group), key=repr))
