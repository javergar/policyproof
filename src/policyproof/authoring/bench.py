"""How well an extractor reads a policy document, against a hand-written policy and its eval cases (spec, Calls 6):

- no clashes in the extraction;
- every sentence a rule or background (the uncovered sentences are listed for a person to judge);
- for every case's facts (given and expected), the extraction decides what the hand-written policy decides.

Names differ between extractions, so a map from extracted names to reference names (variables, outcomes, sorts and
enum values) is written once per policy. Run: `python -m policyproof.authoring.bench --model MODEL DOC CASES [NAMES]`.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import yaml
from returns.result import Failure, Result, Success

from policyproof.authoring.document import Anchor, Document, parse
from policyproof.authoring.ports import Extractor
from policyproof.core._result import unreachable
from policyproof.core.decide import Decided, Decision, decide
from policyproof.core.facts import Answered, Fact, Facts, FromSystem, all_facts, facts
from policyproof.core.problems import Clash, OutrightConflict, problems
from policyproof.core.solver import Compiled, compile
from policyproof.core.syntax import Ask, CheckedPolicy, EnumLit, Lit, System
from policyproof.effects.errors import LLMError, describe
from policyproof.eval.cases import CaseFile, ReplyCase, TurnCase
from policyproof.eval.cases import load as load_cases


@dataclass(frozen=True, slots=True)
class BenchResult:
    clashes: int
    uncovered: tuple[Anchor, ...]
    decisions_matched: int
    decisions_total: int
    mismatches: tuple[str, ...]  # "<case id>: <what differs>"


def _case_facts(p: CheckedPolicy, case: TurnCase | ReplyCase) -> Facts:
    extra: list[Fact] = []
    if isinstance(case, TurnCase):
        roles = {v.name: v.role for v in p.variables}
        for var, value in case.expect_facts:
            role = roles.get(var)
            extra.append(Fact(var, value, Answered(role.question, "case") if isinstance(role, Ask)
                              else FromSystem("case")))
    return facts(*all_facts(case.facts), *extra)


def _label(d: Decision, outcome_name: Mapping[str, str]) -> str:
    return f"outcome {outcome_name.get(d.outcome, d.outcome)}" if isinstance(d, Decided) else type(d).__name__


def _translate(c: Compiled, fs: Facts, back: Mapping[str, str]) -> Facts | str:
    """Reference facts in the extraction's names, or why they can't be given to it."""
    inputs = {v.name: v for v in c.policy.variables if isinstance(v.role, System | Ask)}
    out: list[Fact] = []
    for f in all_facts(fs):
        var = back.get(f.var, f.var)
        if var not in inputs:
            return f"the extraction has no input for {f.var}"
        value: Lit = f.value
        if isinstance(value, EnumLit):
            value = EnumLit(back.get(value.sort, value.sort), back.get(value.value, value.value))
        role = inputs[var].role
        out.append(Fact(var, value, Answered(role.question, "case") if isinstance(role, Ask) else FromSystem("case")))
    return facts(*out)


async def bench(doc: Document, cases: CaseFile, names: Mapping[str, str],
                extractor: Extractor) -> Result[BenchResult, LLMError]:
    match await extractor.extract(doc):
        case Success(ex):
            pass
        case Failure(e):
            return Failure(e)
        case _:
            unreachable()
    reference, extracted = compile(cases.policy), compile(ex.policy)
    found = problems(extracted).found
    clashes = sum(isinstance(f, Clash | OutrightConflict) for f in found)
    back = {ref: mine for mine, ref in names.items()}
    matched, mismatches = 0, []
    for case in cases.cases:
        fs = _case_facts(cases.policy, case)
        want = _label(decide(reference, fs), {})
        mapped = _translate(extracted, fs, back)
        got = mapped if isinstance(mapped, str) else _label(decide(extracted, mapped), names)
        if got == want:
            matched += 1
        else:
            mismatches.append(f"{case.id}: expected {want}, got {got}")
    return Success(BenchResult(clashes, ex.uncovered, matched, len(cases.cases), tuple(mismatches)))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m policyproof.authoring.bench")
    parser.add_argument("--model", required=True, help="a pydantic-ai model string")
    parser.add_argument("doc", type=Path)
    parser.add_argument("cases", type=Path)
    parser.add_argument("names", type=Path, nargs="?", help="YAML: extracted name -> reference name")
    args = parser.parse_args(argv)
    from pydantic_ai.models import infer_model

    from policyproof.authoring.llm.extractor import LLMExtractor
    case_file = load_cases(args.cases)
    if isinstance(case_file, Failure):
        print(f"{args.cases}: {case_file.failure()}", file=sys.stderr)
        return 2
    names = yaml.safe_load(args.names.read_text()) if args.names else {}
    result = asyncio.run(bench(parse(args.doc.read_text()), case_file.unwrap(), names or {},
                               LLMExtractor(infer_model(args.model))))
    match result:
        case Success(r):
            print(f"clashes: {r.clashes}\ndecisions: {r.decisions_matched}/{r.decisions_total}")
            print("uncovered:" + "".join(f"\n  - {a.text}" for a in r.uncovered))
            print("mismatches:" + "".join(f"\n  - {m}" for m in r.mismatches))
            return 0 if r.clashes == 0 and not r.mismatches else 1
        case Failure(e):
            print(f"extraction failed: {describe(e)}", file=sys.stderr)
            return 2
        case _:
            unreachable()


if __name__ == "__main__":
    sys.exit(main())
