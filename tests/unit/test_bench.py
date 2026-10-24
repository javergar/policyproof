"""The extractor benchmark: a perfect extraction scores full marks, a wrong rule names the cases it gets wrong."""
import asyncio
from dataclasses import replace
from pathlib import Path

from authoring_fakes import Extractor
from returns.result import Success

from policyproof.authoring.bench import BenchResult, bench
from policyproof.authoring.document import parse
from policyproof.authoring.extraction import Extraction
from policyproof.authoring.merge import _rename_rule
from policyproof.core.syntax import CheckedPolicy, Var, When
from policyproof.eval.cases import load as load_cases

EXAMPLES = Path(__file__).parent.parent.parent / "examples"
CASES = load_cases(EXAMPLES / "eval" / "toy.cases.yaml").unwrap()
DOC = parse((EXAMPLES / "authoring" / "toy.md").read_text())


def scored(policy: CheckedPolicy) -> BenchResult:
    extractor = Extractor([Success(Extraction(policy, (), ()))])
    return asyncio.run(bench(DOC, CASES, {}, extractor)).unwrap()


def test_bench_scores_a_perfect_extraction():
    result = scored(CASES.policy)
    assert result.clashes == 0 and result.mismatches == ()
    assert result.decisions_matched == result.decisions_total == len(CASES.cases)


def test_bench_names_the_cases_a_wrong_rule_gets_wrong():
    flipped = tuple(replace(r, then=Var("voucher")) if isinstance(r, When) and r.id == "T2" else r
                    for r in CASES.policy.rules)
    result = scored(CheckedPolicy(replace(CASES.policy, rules=flipped)))
    assert result.decisions_matched < result.decisions_total
    assert result.mismatches and all(m.split(":")[0] in {c.id for c in CASES.cases} for m in result.mismatches)


def test_names_map_extracted_names_to_the_reference():
    """The extraction calls wantsRefund moneyBack; the name map says they're the same thing."""
    p = CASES.policy
    variables = tuple(replace(v, name="moneyBack") if v.name == "wantsRefund" else v for v in p.variables)
    rules = tuple(_rename_rule(r, "wantsRefund", "moneyBack") for r in p.rules)
    extractor = Extractor([Success(Extraction(CheckedPolicy(replace(p, variables=variables, rules=rules)), (), ()))])
    result = asyncio.run(bench(DOC, CASES, {"moneyBack": "wantsRefund"}, extractor)).unwrap()
    assert result.mismatches == () and result.decisions_matched == result.decisions_total
