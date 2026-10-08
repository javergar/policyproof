"""The evaluation report: per reader configuration, every case's grade (the worst of its runs), totals, held-out
totals, the gate, and the text and JSON forms of all of it. Pure.
"""
import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import assert_never

from returns.result import Failure, Result, Success

from policyproof.eval.grade import Conservative, Correct, Grade, Wrong, worst


@dataclass(frozen=True, slots=True)
class RunResult:
    run: int  # 1-based
    grade: Grade
    seconds: float
    trace: tuple[str, ...]  # what the run did, as lines of text (written by the runner)


@dataclass(frozen=True, slots=True)
class CaseResult:
    case: str
    held_out: bool
    grade: Grade  # the worst over its runs
    runs: tuple[RunResult, ...]


@dataclass(frozen=True, slots=True)
class Totals:
    correct: int
    conservative: int
    wrong: int  # counts of cases

    @property
    def cases(self) -> int:
        return self.correct + self.conservative + self.wrong


@dataclass(frozen=True, slots=True)
class ConfigurationResult:
    name: str
    cases: tuple[CaseResult, ...]
    totals: Totals
    held_out: Totals


@dataclass(frozen=True, slots=True)
class Report:
    policy: str
    runs: int
    configurations: tuple[ConfigurationResult, ...]


@dataclass(frozen=True, slots=True)
class GateResult:
    passed: bool
    reasons: tuple[str, ...]  # why it failed; empty when it passed


def case_result(case: str, held_out: bool, runs: tuple[RunResult, ...]) -> CaseResult:
    return CaseResult(case, held_out, worst(r.grade for r in runs), runs)


def totals(cases: Sequence[CaseResult]) -> Totals:
    kinds = [type(c.grade) for c in cases]
    return Totals(kinds.count(Correct), kinds.count(Conservative), kinds.count(Wrong))


def configuration_result(name: str, cases: Sequence[CaseResult]) -> ConfigurationResult:
    return ConfigurationResult(name, tuple(cases), totals(cases), totals([c for c in cases if c.held_out]))


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def _share(t: Totals) -> float:
    return t.conservative / t.cases if t.cases else 0.0


def _gate_reasons(t: Totals, max_conservative: float, prefix: str) -> list[str]:
    reasons: list[str] = []
    if t.wrong:
        reasons.append(f"{prefix}{_plural(t.wrong, 'wrong case')}")
    if _share(t) > max_conservative:
        reasons.append(f"{prefix}{_share(t):.0%} conservative (max {max_conservative:.0%})")
    return reasons


def gate(r: ConfigurationResult, max_conservative: float = 0.1) -> GateResult:
    """Zero wrong cases and at most `max_conservative` of them conservative, over all cases and over the held-out
    cases alone (with no held-out cases, that half passes)."""
    reasons = _gate_reasons(r.totals, max_conservative, "") + _gate_reasons(r.held_out, max_conservative, "held out: ")
    return GateResult(not reasons, tuple(reasons))


# ---- text


def _label(g: Grade) -> str:
    match g:
        case Correct():
            return "correct"
        case Conservative(reason):
            return f"conservative: {reason}"
        case Wrong(reason):
            return f"wrong: {reason}"
        case _:
            assert_never(g)


def _counts(t: Totals) -> str:
    return f"{_plural(t.cases, 'case')}: {t.correct} correct, {t.conservative} conservative, {t.wrong} wrong"


def _case_lines(c: CaseResult) -> list[str]:
    held = " (held out)" if c.held_out else ""
    head = (f"  WRONG {c.case}{held}: {c.grade.reason}" if isinstance(c.grade, Wrong)
            else f"  conservative {c.case}{held}: {c.grade.reason}" if isinstance(c.grade, Conservative) else "")
    lines = [head]
    for r in c.runs:
        lines.append(f"    run {r.run} ({r.seconds:.1f}s): {_label(r.grade)}")
        if not isinstance(r.grade, Correct):
            lines += [f"      {t}" for t in r.trace]
    return lines


def render_text(report: Report, max_conservative: float = 0.1) -> str:
    lines = [f"policy {report.policy}, {_plural(report.runs, 'run')} per case"]
    for r in report.configurations:
        g = gate(r, max_conservative)
        lines += ["", f"{r.name}: PASS" if g.passed else f"{r.name}: FAIL ({'; '.join(g.reasons)})",
                  f"  {_counts(r.totals)} ({_share(r.totals):.0%} conservative, max {max_conservative:.0%})"]
        if r.held_out.cases:
            lines.append(f"  held out: {_counts(r.held_out)}")
        for kind in (Wrong, Conservative):
            for c in r.cases:
                if isinstance(c.grade, kind):
                    lines += _case_lines(c)
    return "\n".join(lines) + "\n"


# ---- JSON


def _grade_data(g: Grade) -> dict[str, str]:
    match g:
        case Correct():
            return {"grade": "correct"}
        case Conservative(reason):
            return {"grade": "conservative", "reason": reason}
        case Wrong(reason):
            return {"grade": "wrong", "reason": reason}
        case _:
            assert_never(g)


def to_json(report: Report) -> str:
    return json.dumps({"policy": report.policy, "runs": report.runs, "configurations": [
        {"name": r.name, "cases": [
            {"case": c.case, "held_out": c.held_out, "runs": [
                {"run": x.run, **_grade_data(x.grade), "seconds": x.seconds, "trace": list(x.trace)} for x in c.runs]}
            for c in r.cases]}
        for r in report.configurations]}, indent=1)


def _grade(d: dict[str, object]) -> Grade:
    match d["grade"]:
        case "correct":
            return Correct()
        case "conservative":
            return Conservative(str(d["reason"]))
        case "wrong":
            return Wrong(str(d["reason"]))
        case other:
            raise ValueError(f"unknown grade {other!r}")


def from_json(text: str) -> Result[Report, str]:
    """A report written by `to_json`. Totals and case grades are recomputed from the runs."""
    try:
        data = json.loads(text)
        return Success(Report(str(data["policy"]), int(data["runs"]), tuple(
            configuration_result(str(r["name"]), [
                case_result(str(c["case"]), bool(c["held_out"]), tuple(
                    RunResult(int(x["run"]), _grade(x), float(x["seconds"]), tuple(str(t) for t in x["trace"]))
                    for x in c["runs"]))
                for c in r["cases"]])
            for r in data["configurations"])))
    except (ValueError, KeyError, TypeError) as e:
        return Failure(f"not a report: {type(e).__name__}: {e}")
