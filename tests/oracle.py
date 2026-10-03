"""A brute-force oracle: enumerate every world of the finite variables (p, q, r, c) and judge a claim directly."""
from itertools import product

from strategies import COLOR, FINITE

from policyproof.core.semantics import evaluate, rule_expr
from policyproof.core.syntax import BoolLit, EnumLit, Expr, Lit, Rule

WORLDS: list[dict[str, Lit]] = [
    {"p": BoolLit(p), "q": BoolLit(q), "r": BoolLit(r), "c": EnumLit("Color", c)}
    for p, q, r, c in product((False, True), (False, True), (False, True), COLOR.values)
]
assert len(WORLDS) == 24 and all(set(w) == set(FINITE) for w in WORLDS)


def holds(e: Expr, world: dict[str, Lit]) -> bool:
    return evaluate(e, world).unwrap() == BoolLit(True)


def judge(rules: tuple[Rule, ...], given: dict[str, Lit], claim: Expr) -> str:
    """'proven' | 'refuted' | 'contingent' | 'inconsistent', by checking every world."""
    allowed = [w for w in WORLDS if all(holds(rule_expr(r), w) for r in rules)
               and all(w[k] == v for k, v in given.items())]
    if not allowed:
        return "inconsistent"
    truths = {holds(claim, w) for w in allowed}
    return "proven" if truths == {True} else "refuted" if truths == {False} else "contingent"
