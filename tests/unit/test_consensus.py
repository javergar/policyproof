import asyncio
import logging

from fakes import Answers, Claims, Facts
from returns.result import Failure, Success

from policyproof.core.facts import Quoted, Scored
from policyproof.effects.consensus import AgreeingAnswers, AgreeingFacts, UnionClaims
from policyproof.effects.errors import Unavailable
from policyproof.effects.ports import NotAnswered, RawClaim, RawFact, Said, Unclear

MSG = "It came by courier and I'd like my money back."
DOWN = Failure(Unavailable("down"))


def test_facts_both_readers_agree_on_are_kept_with_the_best_evidence(toy):
    llm = Facts(Success((RawFact("carrier", "COURIER", Quoted("by courier")), RawFact("wantsRefund", True,
                                                                                       Quoted("money back")))))
    jev = Facts(Success((RawFact("carrier", "COURIER", Scored(0.9)), RawFact("wantsRefund", "false", Scored(0.7)))))
    got = asyncio.run(AgreeingFacts(jev, llm).read_facts(toy, MSG))
    assert got == Success((RawFact("carrier", "COURIER", Quoted("by courier")),))


def test_scored_evidence_keeps_the_lower_confidence(toy):
    a = Facts(Success((RawFact("wantsRefund", "true", Scored(0.9)),)))
    b = Facts(Success((RawFact("wantsRefund", True, Scored(0.6)),)))
    assert asyncio.run(AgreeingFacts(a, b).read_facts(toy, MSG)) == Success((RawFact("wantsRefund", "true",
                                                                                       Scored(0.6)),))


def test_a_disagreement_is_logged(toy, caplog):
    a = Facts(Success((RawFact("wantsRefund", True, Scored(0.9)),)))
    b = Facts(Success((RawFact("wantsRefund", False, Scored(0.9)),)))
    with caplog.at_level(logging.WARNING, logger="policyproof.consensus"):
        assert asyncio.run(AgreeingFacts(a, b).read_facts(toy, MSG)) == Success(())
    assert "readers disagree on wantsRefund" in caplog.text


def test_one_failed_reader_leaves_the_other_and_is_logged(toy, caplog):
    ok = Facts(Success((RawFact("wantsRefund", True, Scored(0.9)),)))
    with caplog.at_level(logging.WARNING, logger="policyproof.consensus"):
        assert asyncio.run(AgreeingFacts(ok, Facts(DOWN)).read_facts(toy, MSG)) == ok.result
    assert "one reader failed" in caplog.text
    assert asyncio.run(AgreeingFacts(Facts(DOWN), Facts(Failure(Unavailable("also")))).read_facts(toy, MSG)) == DOWN


def test_answers_must_agree(toy):
    def both(a, b):
        return asyncio.run(AgreeingAnswers(Answers(Success(a)), Answers(Success(b))).read_answer(toy, "wantsRefund",
                                                                                                    "Yes, money back"))
    assert both(Said(True, "money back"), Said("true", "Yes")) == Success(Said(True, "money back"))
    assert both(Said(True, "nowhere"), Said("true", "Yes")) == Success(Said(True, "Yes"))
    assert both(Said(True, "Yes"), Said(False, "Yes")) == Success(Unclear("readers disagree"))
    assert both(NotAnswered(), NotAnswered()) == Success(NotAnswered())
    assert both(NotAnswered(), Said(True, "Yes")) == Success(Unclear("readers disagree"))


def test_claims_are_the_union(toy):
    a = Claims([Success((RawClaim("refund", "a refund"), RawClaim({"not": "voucher"}, "no voucher")))])
    b = Claims([Success((RawClaim({"not": "voucher"}, "no voucher"), RawClaim("isLate", "it was late")))])
    got = asyncio.run(UnionClaims(a, b).read_claims(toy, "reply"))
    assert got == Success((RawClaim("refund", "a refund"), RawClaim({"not": "voucher"}, "no voucher"),
                           RawClaim("isLate", "it was late")))
