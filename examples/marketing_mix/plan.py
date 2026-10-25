"""A media plan for a budget: an optimizer picks the most profitable split, and policyproof proves it follows the
guidelines. Z3 only, no model.

    uv run python examples/marketing_mix/plan.py

`planning_data.json` stands in for the planning tools: each SKU's margin, stock and launch status, each channel's
funnel stage, and funnel performance per SKU and channel (revenue per dollar, falling as spend saturates). The
guidelines in `guidelines.md` are written as `policy.yaml`. The optimizer maximises margin under that policy's own
rules, so the guidelines exist once; then the plan is checked by `decide` like any other case, which names the rules
that approve it, asks the one question still open, or refuses a plan and says which guidelines it breaks.

At this size Z3 optimises directly over the compiled policy. For a large catalogue, use a linear-programming solver
(HiGHS, OR-Tools) for the search and keep `decide` as the final proof.
"""
from __future__ import annotations

import json
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

import z3
from returns.result import Failure, Result

from policyproof.core.codec import from_yaml
from policyproof.core.decide import Decided, Decision, NeedInfo, decide, fact_assertions
from policyproof.core.facts import Answered, Fact, FromSystem, facts
from policyproof.core.solver import Compiled, RuleLabel, Unsat, check, compile, fact, to_z3
from policyproof.core.syntax import Ask, BoolLit, Define, RealLit
from policyproof.core.validate import Finding, gate

HERE = Path(__file__).parent
CHANNELS = ("Tv", "Social", "Search", "Retail")

# Finance's proposed guideline. With G1 (stay within budget) and G5 (25% upper funnel) no plan can follow it.
FINANCE_G8 = """  - id: G8
    source: G8
    explain: At least 80% of the budget goes to the lower funnel.
    when: approved
    then: { ge: [{ add: [search, retail] }, { mul: [{ real: "0.8" }, budget] }] }
"""


@dataclass(frozen=True, slots=True)
class Sku:
    key: str
    name: str
    margin: Fraction
    stock_weeks: Fraction
    launching: bool


@dataclass(frozen=True, slots=True)
class Data:
    budget: Fraction
    legal: bool | None
    skus: tuple[Sku, ...]
    channel_names: Mapping[str, str]
    curves: Mapping[str, tuple[tuple[Fraction, Fraction], ...]]  # spend variable -> (block width, revenue per dollar)
    last_quarter: Mapping[str, Fraction]


@dataclass(frozen=True, slots=True)
class Plan:
    spend: Mapping[str, Fraction]  # spend variable (e.g. "aeroTv") -> thousands of dollars
    margin: Fraction  # predicted margin after media cost


@dataclass(frozen=True, slots=True)
class NoPlan:
    guidelines: tuple[str, ...]  # the guidelines no plan can follow together, for this data


def _q(x: float | int | str) -> Fraction:
    return Fraction(str(x))


def load_data(path: Path) -> Data:
    raw = json.loads(path.read_text())
    perf = raw["performance"]
    skus = tuple(Sku(s["key"], s["name"], _q(s["margin"]), _q(s["stockWeeks"]), s["launching"]) for s in raw["skus"])
    curves = {
        f"{s.key}{ch}": tuple((_q(perf["block"]), _q(perf["revenuePerDollar"][s.key][ch])
                               * _q(perf["saturation"][ch]) ** i) for i in range(perf["blocks"]))
        for s in skus for ch in CHANNELS}
    return Data(_q(raw["budget"]), raw["legalSignedOff"], skus, {c["key"]: c["name"] for c in raw["channels"]},
                curves, {k: _q(v) for k, v in raw["lastQuarter"].items()})


def guidelines(text: str) -> Result[Compiled, tuple[Finding, ...]]:
    """The policy, refused if it has errors (rules that clash, or an outcome no plan can reach)."""
    return gate(compiled_anyway(text))


def compiled_anyway(text: str, extra: str = "") -> Compiled:
    return compile(from_yaml(with_rule(text, extra) if extra else text).unwrap())


def with_rule(text: str, rule: str) -> str:
    """The policy with one more rule, placed before the last one."""
    at = text.rindex("\n  - id: C1")
    return text[:at + 1] + rule + text[at + 1:]


def _known(c: Compiled, data: Data, legal: bool | None) -> list[Fact]:
    tools = FromSystem("planning tools")
    out = [Fact("budget", RealLit(data.budget), tools)]
    for s in data.skus:
        out += [Fact(f"{s.key}StockWeeks", RealLit(s.stock_weeks), tools),
                Fact(f"{s.key}Launching", BoolLit(s.launching), tools)]
    if legal is not None:
        role = next(v.role for v in c.policy.variables if v.name == "legalSignedOff")
        assert isinstance(role, Ask)
        out.append(Fact("legalSignedOff", BoolLit(legal), Answered(role.question, "yes" if legal else "no")))
    return out


def _plan_facts(spend: Mapping[str, Fraction]) -> list[Fact]:
    return [Fact(var, RealLit(v), FromSystem("media plan")) for var, v in spend.items()]


def _real(c: Compiled, x: Fraction) -> z3.ArithRef:
    return z3.RealVal(f"{x.numerator}/{x.denominator}", c.ctx)


def margin_of(data: Data, spend: Mapping[str, Fraction]) -> Fraction:
    """Predicted margin: each block of spend earns its revenue per dollar times the SKU's margin, less its cost."""
    margin = {s.key: s.margin for s in data.skus}
    total = Fraction(0)
    for var, amount in spend.items():
        rate, left = margin[var.removesuffix(next(ch for ch in CHANNELS if var.endswith(ch)))], amount
        for width, rpd in data.curves[var]:
            used = min(left, width)
            total += used * (rate * rpd - 1)
            left -= used
        total -= left  # beyond the last block the spend earns nothing
    return total


def optimise(c: Compiled, data: Data, *, legal: bool) -> Plan | NoPlan:
    """The most profitable plan the guidelines approve. An approval not given yet (`legal`) is taken as no."""
    o = z3.Optimize(ctx=c.ctx)
    o.set("timeout", c.timeout_ms)
    for formula in c.rules.values():
        o.add(formula)
    for _, e in fact_assertions(_known(c, data, legal)):
        o.add(to_z3(c, e))
    o.add(c.variables["approved"])
    margin = {s.key: s.margin for s in data.skus}
    objective: list[z3.ArithRef] = []
    for var, curve in data.curves.items():
        sku = var.removesuffix(next(ch for ch in CHANNELS if var.endswith(ch)))
        blocks = [z3.Real(f"{var}!{i}", c.ctx) for i in range(len(curve))]
        rest = z3.Real(f"{var}!rest", c.ctx)  # spend past the last block: cost, no return
        for b, (width, _) in zip(blocks, curve, strict=True):
            o.add(b >= 0, b <= _real(c, width))
        o.add(rest >= 0, c.variables[var] == z3.Sum([*blocks, rest]))
        objective += [b * _real(c, margin[sku] * rpd - 1) for b, (_, rpd) in zip(blocks, curve, strict=True)]
        objective.append(-rest)
    o.maximize(z3.Sum(objective))
    match o.check():
        case z3.sat:
            m = o.model()
            spend = {var: Fraction(m.eval(c.variables[var], model_completion=True).as_fraction())
                     for var in data.curves}
            return Plan(spend, margin_of(data, spend))
        case _:
            return NoPlan(clash(c, _known(c, data, legal)))


def prove(c: Compiled, data: Data, spend: Mapping[str, Fraction], *, legal: bool | None) -> Decision:
    """The plan decided like any case: approved with the rules that prove it, a question, or refused."""
    return decide(c, facts(*_known(c, data, legal), *_plan_facts(spend)))


def _guideline_vars(c: Compiled) -> dict[str, str]:
    return {r.id: r.var for r in c.policy.rules if isinstance(r, Define) and r.id.startswith("G")}


def broken(c: Compiled, data: Data, spend: Mapping[str, Fraction], *, legal: bool | None) -> tuple[str, ...]:
    """Every guideline the plan is proved to break (not only the first one `decide` finds)."""
    known = fact_assertions([*_known(c, data, legal), *_plan_facts(spend)])
    return tuple(g for g, var in _guideline_vars(c).items()
                 if isinstance(check(c, [*known, fact(var, BoolLit(True))]), Unsat))


def clash(c: Compiled, known: list[Fact] | None = None) -> tuple[str, ...]:
    """The guidelines that together leave no plan approvable (given the known facts, if any)."""
    result = check(c, [*fact_assertions(known or []), fact("approved", BoolLit(True))])
    assert isinstance(result, Unsat), "some plan is approvable"
    return tuple(sorted(label.id for label in result.core if isinstance(label, RuleLabel) and label.id.startswith("G")))


# ---- the report

def _explain(c: Compiled, rule: str) -> str:
    return next(r.explain or rule for r in c.policy.rules if r.id == rule)


def _k(x: Fraction) -> str:
    return f"${float(x):,.1f}k"


def _table(data: Data, spend: Mapping[str, Fraction]) -> str:
    rows = [f"  {'':16}" + "".join(f"{data.channel_names[ch]:>14}" for ch in CHANNELS) + f"{'Total':>12}"]
    for s in data.skus:
        cells = [spend[f"{s.key}{ch}"] for ch in CHANNELS]
        rows.append(f"  {s.name:16}" + "".join(f"{_k(v):>14}" for v in cells) + f"{_k(sum(cells, Fraction(0))):>12}")
    total = sum(spend.values(), Fraction(0))
    rows.append(f"  {'Share of budget':16}" + "".join(
        f"{float(sum(spend[f'{s.key}{ch}'] for s in data.skus) / data.budget):>14.0%}" for ch in CHANNELS)
        + f"{float(total / data.budget):>12.0%}")
    return "\n".join(rows)


def _display(c: Compiled, outcome: str | None) -> str:
    return next((o.display or o.name for o in c.policy.outcomes if o.name == outcome), str(outcome))


def _verdict(c: Compiled, d: Decision) -> str:
    match d:
        case Decided(outcome=outcome, rules=rules):
            cited = [r for r in rules if r.startswith("G")]
            return f"{_display(c, outcome)}: proved from " + ", ".join(cited) + "."
        case NeedInfo(question=q, what_if=what_if):
            answers = "; ".join(f"{'yes' if a == BoolLit(True) else 'no'}: {_display(c, o)}" for a, o in what_if)
            return f"Can't approve yet. Ask: {q} ({answers})"
        case _:
            return str(d)


def main() -> int:
    text = (HERE / "policy.yaml").read_text()
    data = load_data(HERE / "planning_data.json")
    gated = guidelines(text)
    if isinstance(gated, Failure):
        print("The guidelines can't be used:", gated.failure())
        return 1
    c = gated.unwrap()
    legal = bool(data.legal)

    print(f"Budget {_k(data.budget)}. Legal sign-off on the TV creative: "
          f"{ {None: 'not yet', True: 'yes', False: 'no'}[data.legal] }.\n")
    best = optimise(c, data, legal=legal)
    if isinstance(best, NoPlan):
        print("No plan can follow these guidelines together:", ", ".join(best.guidelines))
        return 1
    print(f"1. The best plan the guidelines allow (predicted margin {_k(best.margin)}):\n")
    print(_table(data, best.spend))
    print("\n  " + _verdict(c, prove(c, data, best.spend, legal=data.legal)))

    if not legal:
        tv = optimise(c, data, legal=True)
        if isinstance(tv, Plan):
            print(f"\n2. With legal sign-off, TV opens up: predicted margin {_k(tv.margin)} "
                  f"({_k(tv.margin - best.margin)} more):\n")
            print(_table(data, tv.spend))
            print("\n  " + _verdict(c, prove(c, data, tv.spend, legal=data.legal)))

    print("\n3. Last quarter's plan, checked against the guidelines (with legal sign-off):\n")
    print(_table(data, data.last_quarter))
    print("\n  " + _verdict(c, prove(c, data, data.last_quarter, legal=True)))
    for g in broken(c, data, data.last_quarter, legal=True):
        print(f"  Breaks {g}: {_explain(c, g)}")

    print("\n4. Finance proposes G8, 'At least 80% of the budget goes to the lower funnel':\n")
    refused = guidelines(with_rule(text, FINANCE_G8))
    assert isinstance(refused, Failure)
    with_g8 = compiled_anyway(text, FINANCE_G8)
    print("  Refused before any plan is made: no plan could ever be approved. It clashes with:")
    for g in clash(with_g8):
        if g != "G8":
            print(f"  {g}: {_explain(with_g8, g)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
