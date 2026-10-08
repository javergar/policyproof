"""`policyproof eval` end to end, with a scripted pydantic-ai model standing in for every reader."""
import json

import pytest
from conftest import POLICIES
from pydantic_ai.messages import ModelMessage, ModelRequest, ModelResponse, TextPart, ToolCallPart, UserPromptPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from policyproof.eval.cli import main
from policyproof.eval.report import from_json

CASES = f"""\
policy: {POLICIES / "toy.yaml"}
cases:
  - id: says-yes
    turn: {{facts: {{daysLate: 3}}, asked: wantsRefund, message: "Yes, money back please."}}
    expect: {{decision: refund}}
  - id: voucher-draft
    reply: {{facts: {{daysLate: 3, wantsRefund: true}}, draft: "You'll get a voucher."}}
    expect: caught
"""
READERS = """\
models: {fake: test}
configurations:
  fake-only: {answers: fake, facts: fake, claims: fake, rewriter: fake}
"""


def scripted(misread_vouchers: bool = False) -> FunctionModel:
    """Answers yes, finds no facts, reads claims from the reply (or misreads a voucher as a refund), rewrites well."""
    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        text = next(str(p.content) for m in messages if isinstance(m, ModelRequest) for p in m.parts
                    if isinstance(p, UserPromptPart))
        task = info.instructions or ""
        if task.startswith("You rewrite"):
            return ModelResponse(parts=[TextPart("You'll get a refund.")])
        if task.startswith("You read a customer's reply"):
            out: object = {"status": "answered", "value": True, "quote": "money back"}
        elif task.startswith("You find facts"):
            out = {"facts": []}
        elif "voucher" in text:
            out = {"claims": [{"expr": "refund" if misread_vouchers else "voucher", "quote": "get a voucher"}]}
        else:
            out = {"claims": [{"expr": "refund", "quote": "get a refund"}]}
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, json.dumps(out))])
    return FunctionModel(respond)


@pytest.fixture
def files(tmp_path):
    (tmp_path / "cases.yaml").write_text(CASES)
    (tmp_path / "readers.yaml").write_text(READERS)
    return tmp_path


def run(files, *extra, model=None):
    return main(["eval", str(files / "cases.yaml"), "--readers", str(files / "readers.yaml"), "--runs", "1", *extra],
                models={"fake": model or scripted()})


def test_a_passing_gate_exits_0_and_prints_the_report(files, capsys):
    assert run(files) == 0
    out = capsys.readouterr().out
    assert "fake-only: PASS" in out and "2 cases: 2 correct, 0 conservative, 0 wrong" in out


def test_a_wrong_case_fails_the_gate_with_exit_1(files, capsys):
    assert run(files, model=scripted(misread_vouchers=True)) == 1
    assert "WRONG voucher-draft: the draft was sent as written" in capsys.readouterr().out


def test_the_json_report_can_be_read_back(files):
    assert run(files, "--json", str(files / "report.json")) == 0
    report = from_json((files / "report.json").read_text()).unwrap()
    assert report.configurations[0].name == "fake-only"


def test_invalid_inputs_exit_2_before_any_model_is_called(files, capsys):
    (files / "bad.yaml").write_text(CASES.replace("decision: refund", "decision: jackpot"))
    assert main(["eval", str(files / "bad.yaml"), "--readers", str(files / "readers.yaml")]) == 2
    assert "cases[0].expect.decision: unknown outcome 'jackpot'" in capsys.readouterr().err
    (files / "r.yaml").write_text(READERS.replace("claims: fake", "claims: gpt"))
    assert main(["eval", str(files / "cases.yaml"), "--readers", str(files / "r.yaml")]) == 2
    assert run(files, "--only", "nope") == 2
    assert "no configuration named 'nope'" in capsys.readouterr().err


def test_only_selects_configurations(files, capsys):
    other = "  other: {answers: fake, facts: fake, claims: fake, rewriter: fake}\n"
    (files / "readers.yaml").write_text(READERS + other)
    assert run(files, "--only", "other") == 0
    out = capsys.readouterr().out
    assert "other: PASS" in out and "fake-only" not in out


def test_only_builds_the_selected_configurations_models(files, capsys):
    unusable = "  needs-a-key: {answers: jev, facts: jev, claims: fake, rewriter: fake}\n"
    (files / "readers.yaml").write_text(READERS.replace("{fake: test}", "{fake: test, jev: 'nosuchprovider:x'}")
                                        + unusable)
    assert run(files, "--only", "fake-only") == 0


@pytest.mark.parametrize(("extra", "message"), [
    (("--runs", "0"), "--runs must be at least 1"),
    (("--concurrency", "0"), "--concurrency must be at least 1"),
    (("--max-conservative", "1.5"), "--max-conservative must be between 0 and 1"),
    (("--json", "/no/such/dir/report.json"), "can't write the report: /no/such/dir does not exist"),
])
def test_bad_options_exit_2_before_any_model_is_called(files, capsys, extra, message):
    calls = []

    def never(messages, info):
        calls.append(1)
        raise AssertionError("a model was called")
    assert run(files, *extra, model=FunctionModel(never)) == 2
    assert message in capsys.readouterr().err and not calls


def test_a_case_file_without_cases_exits_2(files, capsys):
    (files / "empty.yaml").write_text(f"policy: {POLICIES / 'toy.yaml'}\ncases: []\n")
    assert main(["eval", str(files / "empty.yaml"), "--readers", str(files / "readers.yaml")]) == 2
    assert "has no cases" in capsys.readouterr().err
