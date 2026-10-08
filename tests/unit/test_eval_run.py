import asyncio
from dataclasses import dataclass

from conftest import POLICIES
from fakes import Answers, Claims, Facts, Rewriter
from returns.result import Failure, Result, Success

from policyproof.core.syntax import CheckedPolicy
from policyproof.effects.errors import LLMError, Unavailable
from policyproof.effects.ports import RawAnswer, RawClaim, Said
from policyproof.eval.cases import decode
from policyproof.eval.grade import Conservative, Correct, Wrong
from policyproof.eval.run import Configuration, evaluate

CASES = decode({"policy": str(POLICIES / "toy.yaml"), "cases": [
    {"id": "says-yes", "turn": {"facts": {"daysLate": 3}, "asked": "wantsRefund", "message": "Yes, money back please."},
     "expect": {"decision": "refund", "facts": {"wantsRefund": True}}},
    {"id": "voucher-draft", "held_out": True,
     "reply": {"facts": {"daysLate": 3, "wantsRefund": True}, "draft": "You'll get a voucher."}, "expect": "caught"},
]}, POLICIES).unwrap()
NO_FACTS = Facts(Success(()))
VOUCHER = Success((RawClaim("voucher", "get a voucher"),))
REFUND = Success((RawClaim("refund", "get a refund"),))


def config(name="fake", answers=None, claims=None, rewriter=None):
    return Configuration(name, answers or Answers(Success(Said(True, "money back"))), NO_FACTS,
                         claims or Claims([VOUCHER, REFUND]), rewriter or Rewriter(Success("You'll get a refund.")))


def test_every_case_runs_the_given_number_of_times_and_is_graded():
    report = asyncio.run(evaluate(CASES, [config()], runs=2))
    assert report.policy == "toy-delivery" and report.runs == 2
    [r] = report.configurations
    assert [(c.case, c.held_out, c.grade, len(c.runs)) for c in r.cases] == [
        ("says-yes", False, Correct(), 2), ("voucher-draft", True, Correct(), 2)]


def test_a_turn_trace_shows_the_decision_and_what_was_read():
    report = asyncio.run(evaluate(CASES, [config()], runs=1))
    trace = report.configurations[0].cases[0].runs[0].trace
    assert trace[0] == "decision: decided refund (rules T1, T2)"
    assert 'read wantsRefund = true (answered: "money back")' in trace


def test_a_reply_trace_shows_what_was_sent_and_why():
    report = asyncio.run(evaluate(CASES, [config()], runs=1))
    trace = report.configurations[0].cases[1].runs[0].trace
    assert trace[:2] == ("decision: decided refund (rules T1, T2)", "sent after 2 attempts: You'll get a refund.")
    assert 'claim "get a refund": refund is proven' in trace


def test_reader_errors_are_conservative():
    down = config(answers=Answers(Failure(Unavailable("down"))))
    case = asyncio.run(evaluate(CASES, [down], runs=1)).configurations[0].cases[0]
    assert case.grade == Conservative("reader error: provider unavailable: down")


@dataclass
class Crashing:
    async def read_answer(self, p: CheckedPolicy, var: str, message: str) -> Result[RawAnswer, LLMError]:
        raise KeyError("boom")


def test_a_crashing_reader_is_wrong_and_the_run_goes_on():
    report = asyncio.run(evaluate(CASES, [config(answers=Crashing())], runs=1))
    turn, reply = report.configurations[0].cases
    assert turn.grade == Wrong("crashed: KeyError: 'boom'") and reply.grade == Correct()


def test_a_bad_draft_sent_as_written_is_wrong():
    misread = Success((RawClaim("refund", "get a voucher"),))  # the reader reads the voucher sentence as a refund
    lets_it_through = config(claims=Claims([misread]))
    case = asyncio.run(evaluate(CASES, [lets_it_through], runs=1)).configurations[0].cases[1]
    assert case.grade == Wrong("the draft was sent as written, expected it to be caught")


@dataclass
class Slow:
    in_flight: int = 0
    most: int = 0

    async def read_answer(self, p: CheckedPolicy, var: str, message: str) -> Result[RawAnswer, LLMError]:
        self.in_flight += 1
        self.most = max(self.most, self.in_flight)
        await asyncio.sleep(0.01)
        self.in_flight -= 1
        return Success(Said(True, "money back"))


def test_at_most_concurrency_jobs_run_at_once():
    slow = Slow()
    asyncio.run(evaluate(CASES, [config(answers=slow)], runs=6, concurrency=2))
    assert slow.most == 2


def test_each_configuration_gets_its_own_result():
    report = asyncio.run(evaluate(CASES, [config("a"), config("b")], runs=1))
    assert [r.name for r in report.configurations] == ["a", "b"]


def test_an_unclear_answer_reads_plainly_in_the_trace():
    vague = config(answers=Answers(Success(Said(False, "money back"))))  # contradicts the opening "Yes"
    trace = asyncio.run(evaluate(CASES, [vague], runs=1)).configurations[0].cases[0].runs[0].trace
    assert "answer unclear: opening contradicts answer" in trace


def test_runs_and_concurrency_must_be_positive():
    import pytest
    for kw in ({"runs": 0}, {"concurrency": 0}):
        with pytest.raises(ValueError, match="at least 1"):
            asyncio.run(evaluate(CASES, [config()], **kw))
