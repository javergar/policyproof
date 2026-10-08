from returns.result import Failure, Success

from policyproof.eval.grade import Conservative, Correct, Wrong
from policyproof.eval.report import (
    GateResult,
    Report,
    RunResult,
    Totals,
    case_result,
    configuration_result,
    from_json,
    gate,
    render_text,
    to_json,
)


def runs(*grades):
    return tuple(RunResult(i + 1, g, 1.5, (f"trace {i + 1}",)) for i, g in enumerate(grades))


OK = case_result("ok", False, runs(Correct(), Correct()))
SHAKY = case_result("shaky", True, runs(Correct(), Conservative("asked again")))
BAD = case_result("bad", False, runs(Wrong("decided voucher, expected refund"), Correct()))


def test_a_case_is_graded_by_its_worst_run_and_totals_count_cases():
    assert SHAKY.grade == Conservative("asked again") and BAD.grade == Wrong("decided voucher, expected refund")
    r = configuration_result("haiku", [OK, SHAKY, BAD])
    assert r.totals == Totals(correct=1, conservative=1, wrong=1)
    assert r.held_out == Totals(correct=0, conservative=1, wrong=0)


def test_the_gate_needs_zero_wrong_cases_and_few_conservative_ones():
    meh = case_result("meh", False, runs(Conservative("asked again")))
    assert gate(configuration_result("a", [OK, OK, OK, OK, OK, OK, OK, OK, OK, meh])) == GateResult(True, ())
    held = gate(configuration_result("a", [OK, OK, OK, OK, OK, OK, OK, OK, OK, SHAKY]))
    assert held == GateResult(False, ("held out: 100% conservative (max 10%)",))  # the held-out cases count alone too
    got = gate(configuration_result("a", [OK, BAD]))
    assert got == GateResult(False, ("1 wrong case",))
    got = gate(configuration_result("a", [OK, OK, OK, SHAKY]), max_conservative=0.2)
    assert got == GateResult(False, ("25% conservative (max 20%)", "held out: 100% conservative (max 20%)"))


def test_a_configuration_without_held_out_cases_passes_that_half():
    assert gate(configuration_result("a", [OK])) == GateResult(True, ())
    assert gate(configuration_result("a", [])) == GateResult(True, ())


def test_the_text_report_lists_totals_the_verdict_and_every_case_that_is_not_correct():
    report = Report("toy-delivery", 2, (configuration_result("haiku", [OK, SHAKY, BAD]),))
    assert render_text(report, max_conservative=0.5) == """\
policy toy-delivery, 2 runs per case

haiku: FAIL (1 wrong case; held out: 100% conservative (max 50%))
  3 cases: 1 correct, 1 conservative, 1 wrong (33% conservative, max 50%)
  held out: 1 case: 0 correct, 1 conservative, 0 wrong
  WRONG bad: decided voucher, expected refund
    run 1 (1.5s): wrong: decided voucher, expected refund
      trace 1
    run 2 (1.5s): correct
  conservative shaky (held out): asked again
    run 1 (1.5s): correct
    run 2 (1.5s): conservative: asked again
      trace 2
"""


def test_reports_round_trip_through_json():
    report = Report("toy-delivery", 2, (configuration_result("haiku", [OK, SHAKY, BAD]),))
    assert from_json(to_json(report)) == Success(report)
    assert isinstance(from_json("{}"), Failure) and isinstance(from_json("not json"), Failure)
