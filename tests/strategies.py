"""Hypothesis strategies: well-typed expressions, total environments and whole policies over one fixed signature."""
from dataclasses import replace
from functools import cache

from hypothesis import strategies as st

from policyproof.core.syntax import (
    BOOL,
    CMP_OPS,
    INT,
    REAL,
    And,
    Arith,
    Ask,
    BoolLit,
    BoolSort,
    Cmp,
    CmpOp,
    Constraint,
    Define,
    Derived,
    EnumLit,
    EnumSort,
    Expr,
    Iff,
    Implies,
    In,
    IntLit,
    IntSort,
    Lit,
    Not,
    Or,
    Outcome,
    Policy,
    RealLit,
    RealSort,
    Rule,
    Sort,
    System,
    Var,
    Variable,
    When,
)
from policyproof.core.typecheck import Signature

COLOR = EnumSort("Color", ("RED", "GREEN", "BLUE"))
VARS: dict[str, Sort] = {"p": BOOL, "q": BOOL, "r": BOOL, "m": INT, "n": INT, "x": REAL, "c": COLOR}
SIG = Signature({"Color": COLOR}, VARS)


def literals(s: Sort) -> st.SearchStrategy[Lit]:
    match s:
        case BoolSort():
            return st.booleans().map(BoolLit)
        case IntSort():
            return st.integers(-4, 4).map(IntLit)
        case RealSort():
            return st.fractions(-4, 4, max_denominator=4).map(RealLit)
        case EnumSort(name, values):
            return st.sampled_from(values).map(lambda v: EnumLit(name, v))
        case _:
            raise AssertionError(s)


def variables_of(s: Sort) -> st.SearchStrategy[Expr]:
    return st.sampled_from([n for n, t in VARS.items() if t == s]).map(Var)


@cache
def exprs(s: Sort, depth: int = 3, finite: bool = False) -> st.SearchStrategy[Expr]:
    """Well-typed expressions of sort `s` over `SIG`, at most `depth` operators deep. With `finite`, only the
    Bool and Color variables occur, so every world can be enumerated."""
    leaves: st.SearchStrategy[Expr] = st.one_of(literals(s), variables_of(s))
    if depth == 0 or isinstance(s, EnumSort):
        return leaves

    def sub(t: Sort) -> st.SearchStrategy[Expr]:
        return exprs(t, depth - 1, finite)

    def cmp(ops: tuple[CmpOp, ...], t: Sort) -> st.SearchStrategy[Expr]:
        return st.tuples(st.sampled_from(ops), sub(t), sub(t)).map(lambda a: Cmp(a[0], a[1], a[2]))

    if isinstance(s, BoolSort):
        pairs = st.tuples(sub(BOOL), sub(BOOL))
        many = st.lists(sub(BOOL), min_size=2, max_size=3).map(tuple)
        finite_ops = [
            sub(BOOL).map(Not), many.map(And), many.map(Or),
            pairs.map(lambda t: Implies(*t)), pairs.map(lambda t: Iff(*t)),
            cmp(("eq", "ne"), BOOL), cmp(("eq", "ne"), COLOR),
            st.tuples(sub(COLOR), st.lists(literals(COLOR), min_size=1, max_size=3, unique=True)).map(
                lambda t: In(t[0], tuple(t[1]))),
        ]
        numeric_ops = [
            cmp(CMP_OPS, INT), cmp(CMP_OPS, REAL),
            st.tuples(sub(INT), st.lists(literals(INT), min_size=1, max_size=3, unique=True)).map(
                lambda t: In(t[0], tuple(t[1]))),
        ]
        compound = st.one_of(*finite_ops, *([] if finite else numeric_ops))
    else:
        compound = st.one_of(
            st.tuples(st.sampled_from(("add", "mul")), st.lists(sub(s), min_size=2, max_size=3)).map(
                lambda t: Arith(t[0], tuple(t[1]))),
            st.tuples(sub(s), sub(s)).map(lambda t: Arith("sub", t)),
        )
    return st.one_of(leaves, compound)


def envs() -> st.SearchStrategy[dict[str, Lit]]:
    """Total environments: a value for every variable in `SIG`."""
    return st.fixed_dictionaries({n: literals(s) for n, s in VARS.items()})


TEXT = st.text(st.characters(categories=("L", "N", "P", "Zs")), max_size=12)
DECLS = (Variable("p", BOOL, Ask("P?"), "asked"), Variable("q", BOOL, System(), ""),
         Variable("r", BOOL, Derived(), ""), Variable("m", INT, System(), ""), Variable("n", INT, System(), ""),
         Variable("x", REAL, System(), ""), Variable("c", COLOR, System(), ""))


def rules(finite: bool = False) -> st.SearchStrategy[Rule]:
    e = exprs(BOOL, 2, finite)
    meta = st.tuples(st.none() | TEXT, st.none() | TEXT)
    return st.one_of(
        st.tuples(e, e, meta).map(lambda t: When("", t[0], t[1], *t[2])),
        st.tuples(e, meta).map(lambda t: Define("", "r", t[0], *t[1])),
        st.tuples(e, meta).map(lambda t: Constraint("", t[0], *t[1])),
    )


def policies() -> st.SearchStrategy[Policy]:
    """Well-formed policies over `SIG` (they pass `check_policy`)."""
    numbered = st.lists(rules(), max_size=4).map(lambda rs: tuple(replace(r, id=f"R{i}") for i, r in enumerate(rs)))
    outcome = st.lists(st.tuples(st.sampled_from(["p", "q", "r"]), st.booleans()), min_size=1, max_size=2,
                       unique_by=lambda t: t[0])
    outcomes = st.lists(outcome, max_size=3).map(lambda os: tuple(
        Outcome(f"o{i}", tuple((v, BoolLit(b)) for v, b in a)) for i, a in enumerate(os)))
    return st.builds(Policy, name=TEXT, version=TEXT, sorts=st.just((COLOR,)), variables=st.just(DECLS),
                     rules=numbered, outcomes=outcomes)


FINITE = ("p", "q", "r", "c")


def finite_rule_sets() -> st.SearchStrategy[tuple[Rule, ...]]:
    """Up to four rules over the Bool and Color variables only, with ids R0, R1, ..."""
    return st.lists(rules(finite=True), max_size=4).map(
        lambda rs: tuple(replace(r, id=f"R{i}") for i, r in enumerate(rs)))
