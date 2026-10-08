"""The example case files load, and their expectations agree with their policies: a turn whose expected facts are
read decides exactly what the case expects (checked with the core alone, no model)."""
from pathlib import Path

import pytest

from policyproof.core.decide import decide
from policyproof.core.facts import Answered, Fact, FromSystem, merge
from policyproof.core.facts import facts as make_facts
from policyproof.core.solver import compile
from policyproof.core.syntax import Ask
from policyproof.eval.cases import TurnCase, load
from policyproof.eval.config import load_config
from policyproof.eval.grade import Correct, TurnSeen, grade_turn

EXAMPLES = Path(__file__).parent.parent.parent / "examples" / "eval"


@pytest.mark.parametrize("path", sorted(EXAMPLES.glob("*.cases.yaml")), ids=lambda p: p.name)
def test_example_cases_agree_with_their_policy(path):
    f = load(path).unwrap()
    c = compile(f.policy)
    roles = {v.name: v.role for v in f.policy.variables}
    for case in f.cases:
        if not isinstance(case, TurnCase):
            continue
        read = make_facts(*(Fact(var, lit, Answered(r.question, "case") if isinstance(r := roles[var], Ask)
                                 else FromSystem("case")) for var, lit in case.expect_facts))
        known = merge(case.facts, read)
        assert grade_turn(case, TurnSeen(decide(c, known), known)) == Correct(), case.id


def test_the_example_reader_configurations_load():
    names = [s.name for s in load_config(EXAMPLES / "readers.yaml").unwrap().configurations]
    assert names == ["haiku", "jev-and-haiku"]
