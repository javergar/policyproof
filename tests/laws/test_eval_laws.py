"""V1: the gate is monotone (a worse run never turns a failing gate into a passing one) and a case is as bad as its
worst run. V2: reports round-trip through JSON."""
from hypothesis import given
from hypothesis import strategies as st

from policyproof.eval.grade import Conservative, Correct, Wrong, rank
from policyproof.eval.report import Report, RunResult, case_result, configuration_result, from_json, gate, to_json

GRADES = st.one_of(st.just(Correct()), st.builds(Conservative, st.sampled_from(["a", "b"])),
                   st.builds(Wrong, st.sampled_from(["x", "y"])))
RUNS = st.lists(GRADES, min_size=1, max_size=3).map(
    lambda gs: tuple(RunResult(i + 1, g, 0.5, ("t",)) for i, g in enumerate(gs)))
CASES = st.lists(st.tuples(st.booleans(), RUNS), max_size=6).map(
    lambda cs: [case_result(f"c{i}", held, rs) for i, (held, rs) in enumerate(cs)])


@given(CASES, st.data(), st.floats(0, 1))
def test_v1_a_worse_run_never_makes_the_gate_pass(cases, data, bar):
    before = gate(configuration_result("x", cases), max_conservative=bar)
    if not cases:
        return
    i = data.draw(st.integers(0, len(cases) - 1))
    j = data.draw(st.integers(0, len(cases[i].runs) - 1))
    run = cases[i].runs[j]
    worse = data.draw(GRADES.filter(lambda g: rank(g) >= rank(run.grade)))
    changed = list(cases)
    rs = list(cases[i].runs)
    rs[j] = RunResult(run.run, worse, run.seconds, run.trace)
    changed[i] = case_result(cases[i].case, cases[i].held_out, tuple(rs))
    after = gate(configuration_result("x", changed), max_conservative=bar)
    assert before.passed or not after.passed
    assert rank(changed[i].grade) == max(rank(r.grade) for r in rs)


@given(CASES)
def test_v2_reports_round_trip_through_json(cases):
    report = Report("p", 3, (configuration_result("x", cases),))
    assert from_json(to_json(report)).unwrap() == report
