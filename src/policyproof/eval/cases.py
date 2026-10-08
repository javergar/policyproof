"""Evaluation cases: what a user expects of a turn or a reply, read from a YAML file next to their policy.

Every case is checked against the policy before anything runs, so a typo in a case file never costs a model call.
Errors name the YAML path of the problem, e.g. `cases[3].turn.facts.daysLate`.
"""
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml
from returns.result import Failure, Result, Success

from policyproof.core._result import sequence
from policyproof.core.codec import from_yaml
from policyproof.core.facts import Answered, Fact, Facts, FromSystem, facts
from policyproof.core.syntax import Ask, CheckedPolicy, Derived, Lit, System
from policyproof.guards.values import literal_for

ID = re.compile(r"[A-Za-z0-9_-]+\Z")


@dataclass(frozen=True, slots=True)
class OutcomeExpected:
    name: str


@dataclass(frozen=True, slots=True)
class AskExpected:
    var: str


@dataclass(frozen=True, slots=True)
class EscalateExpected:
    pass


type ExpectDecision = OutcomeExpected | AskExpected | EscalateExpected


@dataclass(frozen=True, slots=True)
class TurnCase:
    id: str
    held_out: bool
    facts: Facts
    asked: str | None
    message: str
    expect: ExpectDecision
    expect_facts: tuple[tuple[str, Lit], ...]


@dataclass(frozen=True, slots=True)
class ReplyCase:
    id: str
    held_out: bool
    facts: Facts
    draft: str
    expect: Literal["caught", "pass"]


type Case = TurnCase | ReplyCase


@dataclass(frozen=True, slots=True)
class CaseFile:
    policy: CheckedPolicy
    source: str  # the policy file, as given (resolved against the case file)
    cases: tuple[Case, ...]


@dataclass(frozen=True, slots=True)
class CaseError:
    path: str
    message: str

    def __str__(self) -> str:
        return f"{self.path or '<root>'}: {self.message}"


def _err[T](path: str, message: str) -> Result[T, CaseError]:
    return Failure(CaseError(path, message))


def _map(x: object, path: str, allowed: set[str], required: set[str]) -> Result[Mapping[str, object], CaseError]:
    if not isinstance(x, dict):
        return _err(path, "expected a map")
    for k in x:
        if k not in allowed:
            return _err(f"{path}.{k}" if path else str(k), f"unknown key {k!r}")
    for k in sorted(required - x.keys()):
        return _err(path, f"missing required key {k!r}")
    return Success(x)


def _text(x: object, path: str) -> Result[str, CaseError]:
    if isinstance(x, str):
        return Success(x)
    return _err(path, "expected text (YAML reads yes/no/true/false and numbers as values: quote the text)")


def _given(p: CheckedPolicy, x: object, path: str) -> Result[Facts, CaseError]:
    """Facts the case gives: a system variable's value comes from a system, an askable one was answered."""
    if x is None:
        return Success({})
    if not isinstance(x, dict):
        return _err(path, "expected a map of variable: value")

    def one(var: str, value: object) -> Result[Fact, CaseError]:
        at = f"{path}.{var}"
        v = next((v for v in p.variables if v.name == var), None)
        if v is None:
            return _err(at, f"unknown variable {var!r}")
        match v.role:
            case Derived():
                return _err(at, f"{var} is derived by the rules; a case can't give it")
            case System():
                provenance: FromSystem | Answered = FromSystem("case")
            case Ask(question, _):
                provenance = Answered(question, "case")
        return literal_for(p, var, value).alt(lambda m: CaseError(at, m)).map(lambda lit: Fact(var, lit, provenance))
    return sequence(one(str(k), v) for k, v in x.items()).map(lambda fs: facts(*fs))


def _asked(p: CheckedPolicy, x: object, path: str) -> Result[str, CaseError]:
    def check(var: str) -> Result[str, CaseError]:
        v = next((v for v in p.variables if v.name == var), None)
        if v is not None and isinstance(v.role, Ask):
            return Success(var)
        return _err(path, f"{var!r} is not an ask variable")
    return _text(x, path).bind(check)


def _decision(p: CheckedPolicy, x: object, path: str) -> Result[ExpectDecision, CaseError]:
    outcomes = {o.name for o in p.outcomes}
    match x:
        case str() if x in outcomes:
            return Success(OutcomeExpected(x))
        case "escalate":
            return Success(EscalateExpected())
        case str():
            return _err(path, f"unknown outcome {x!r} (outcomes: {', '.join(sorted(outcomes)) or 'none'})")
        case dict():
            return _map(x, path, {"ask"}, {"ask"}).bind(
                lambda m: _asked(p, m["ask"], f"{path}.ask")).map(AskExpected)
        case _:
            return _err(path, "expected an outcome name, {ask: <variable>} or escalate")


def _expected_facts(p: CheckedPolicy, x: object, path: str, given: Facts
                    ) -> Result[tuple[tuple[str, Lit], ...], CaseError]:
    """Facts the turn must read. One the case already gives, or a derived one, could never test reading."""
    if x is None:
        return Success(())
    if not isinstance(x, dict):
        return _err(path, "expected a map of variable: value")

    def one(var: str, value: object) -> Result[tuple[str, Lit], CaseError]:
        at = f"{path}.{var}"
        v = next((v for v in p.variables if v.name == var), None)
        if v is not None and isinstance(v.role, Derived):
            return _err(at, f"{var} is derived by the rules; a reader never reads it")
        if var in given:
            return _err(at, f"{var} is already given in turn.facts, so reading it would test nothing")
        return literal_for(p, var, value).alt(lambda m: CaseError(at, m)).map(lambda lit: (var, lit))
    return sequence(one(str(k), v) for k, v in x.items())


def _turn(p: CheckedPolicy, cid: str, held: bool, body: object, expect: object, path: str
          ) -> Result[TurnCase, CaseError]:
    at = f"{path}.turn"
    return _map(body, at, {"facts", "asked", "message"}, {"message"}).bind(lambda t: _map(
        expect, f"{path}.expect", {"decision", "facts"}, {"decision"}).bind(lambda e: _given(
            p, t.get("facts"), f"{at}.facts").bind(lambda given: (
                Success(None) if t.get("asked") is None else _asked(p, t["asked"], f"{at}.asked").bind(
                    lambda var: _err(f"{at}.asked", f"{var} is both asked and given in turn.facts; the answer "
                                                    "would be ignored") if var in given else Success(var))).bind(
                lambda asked: _text(t["message"], f"{at}.message").bind(lambda message: _decision(
                    p, e["decision"], f"{path}.expect.decision").bind(lambda decision: _expected_facts(
                        p, e.get("facts"), f"{path}.expect.facts", given).map(lambda want: TurnCase(
                            cid, held, given, asked, message, decision, want))))))))


def _reply(p: CheckedPolicy, cid: str, held: bool, body: object, expect: object, path: str
           ) -> Result[ReplyCase, CaseError]:
    at = f"{path}.reply"
    if expect not in ("caught", "pass"):
        return _err(f"{path}.expect", "a reply case expects caught or pass")
    verdict: Literal["caught", "pass"] = "caught" if expect == "caught" else "pass"
    return _map(body, at, {"facts", "draft"}, {"draft"}).bind(lambda r: _given(p, r.get("facts"), f"{at}.facts").bind(
        lambda given: _text(r["draft"], f"{at}.draft").map(lambda draft: ReplyCase(cid, held, given, draft, verdict))))


def _case(p: CheckedPolicy, x: object, path: str) -> Result[Case, CaseError]:
    def build(m: Mapping[str, object]) -> Result[Case, CaseError]:
        cid = m["id"]
        if not isinstance(cid, str) or not ID.match(cid):
            return _err(f"{path}.id", "an id is letters, digits, - and _")
        held = m.get("held_out", False)
        if not isinstance(held, bool):
            return _err(f"{path}.held_out", "expected true or false")
        if ("turn" in m) == ("reply" in m):
            return _err(path, "a case has exactly one of turn or reply")
        make: Callable[..., Result[Case, CaseError]] = _turn if "turn" in m else _reply
        return make(p, cid, held, m.get("turn", m.get("reply")), m["expect"], path)
    return _map(x, path, {"id", "held_out", "turn", "reply", "expect"}, {"id", "expect"}).bind(build)


def _cases(p: CheckedPolicy, x: object) -> Result[tuple[Case, ...], CaseError]:
    if not isinstance(x, list):
        return _err("cases", "expected a list of cases")
    seen: set[str] = set()
    for i, c in enumerate(x):
        cid = c.get("id") if isinstance(c, dict) else None
        if isinstance(cid, str) and cid in seen:
            return _err(f"cases[{i}].id", f"duplicate id {cid!r}")
        if isinstance(cid, str):
            seen.add(cid)
    return sequence(_case(p, c, f"cases[{i}]") for i, c in enumerate(x))


def _policy(source: str, base: Path) -> Result[CheckedPolicy, CaseError]:
    path = base / source
    try:
        text = path.read_text()
    except OSError as e:
        return _err("policy", f"can't read {path}: {e.strerror}")
    return from_yaml(text).alt(lambda e: CaseError("policy", f"{path}: {e}"))


def decode(data: object, base: Path) -> Result[CaseFile, CaseError]:
    """A case file from plain data (as from `yaml.safe_load`); the policy path is relative to `base`."""
    return _map(data, "", {"policy", "cases"}, {"policy", "cases"}).bind(lambda m: _text(m["policy"], "policy").bind(
        lambda source: _policy(source, base).bind(lambda p: _cases(p, m["cases"]).map(
            lambda cs: CaseFile(p, str(base / source), cs)))))


def load(path: Path) -> Result[CaseFile, CaseError]:
    try:
        data = yaml.safe_load(path.read_text())
    except OSError as e:
        return _err("", f"can't read {path}: {e.strerror}")
    except yaml.YAMLError as e:
        return _err("", f"invalid YAML: {e}")
    return decode(data, path.parent)
