"""An author's answer to a checked change: drafted, applied, re-extracted, merged and checked by Z3."""
import asyncio
from dataclasses import replace

from authoring_fakes import Drafter, Extractor
from conftest import load
from returns.result import Failure, Success

from policyproof.authoring.document import Anchor, Remove, Replace, parse
from policyproof.authoring.examples import Example, holds
from policyproof.authoring.extraction import Extraction, Link
from policyproof.authoring.ports import Choose, Describe
from policyproof.authoring.propose import Draft, EditFailed, Proposal, approve, extract_again, propose, reword
from policyproof.core.problems import Clash, Gap, problems, still_a_problem
from policyproof.core.solver import compile
from policyproof.core.syntax import And, BoolLit, CheckedPolicy, Cmp, EnumLit, IntLit, Not, Var, When
from policyproof.effects.errors import Unavailable

DOC = parse("## Couriers\n\n- Courier parcels are never refunded.\n"
            "- A late courier parcel is refunded if the customer asks. Lost parcels are always refunded.\n\n"
            "## Post\n\nPost parcels that aren't lost are not refunded.\n")
S4, S5, S6, S10 = (s.anchor for s in DOC.sentences)
POLICY = load("defects/couriers.yaml")
BASE = Extraction(POLICY, (Link("C4", S4), Link("C5", S5), Link("C6", S6), Link("C10", S10)), ())
COURIER = Cmp("eq", Var("carrier"), EnumLit("Carrier", "COURIER"))
LATE_ASKED = And((Cmp("gt", Var("daysLate"), IntLit(0)), Var("asked")))
GOOD_TEXT = "Courier parcels are never refunded, unless they arrive late and the customer asks."
GOOD_EDIT = (Replace(S4, GOOD_TEXT),)
POST_LOST = Example("post-lost", (("asked", BoolLit(False)), ("carrier", EnumLit("Carrier", "POST")),
                                  ("daysLate", IntLit(0)), ("lost", BoolLit(True))), "refund")


def part(rule: When, text: str) -> Extraction:
    return Extraction(CheckedPolicy(replace(POLICY, rules=(rule,))), (Link(rule.id, Anchor("Couriers", text)),), ())


GOOD_PART = part(When("x", And((COURIER, Not(LATE_ASKED))), Not(Var("refund"))), GOOD_TEXT)
BAD_PART = part(When("x", Var("asked"), Not(Var("refund"))), GOOD_TEXT)  # refuses everyone who asks


def state(examples=()) -> Draft:
    return Draft(DOC, BASE, tuple(examples))


BEFORE = problems(compile(POLICY))
LATE = next(i for i, f in enumerate(BEFORE.found) if isinstance(f, Clash) and f.rules == ("C4", "C5"))


def consistent(p: Proposal) -> None:
    """Law PR1: what a proposal reports agrees with `still_a_problem` on the policy it proposes."""
    c2, c1 = compile(p.after.extraction.policy), compile(POLICY)
    for i, f in enumerate(BEFORE.found):
        assert isinstance(f, Clash | Gap)
        assert (i in p.fixes) == (not still_a_problem(c2, f))
    for f in p.new:
        assert isinstance(f, Clash | Gap) and not still_a_problem(c1, f) and still_a_problem(c2, f)


def run(coro):
    return asyncio.run(coro)


def test_a_good_answer_fixes_the_clash():
    drafter, extractor = Drafter([Success(GOOD_EDIT)]), Extractor([Success(GOOD_PART)])
    p = run(propose(state(), BEFORE, (LATE,), Choose("refund"), drafter=drafter, extractor=extractor)).unwrap()
    assert LATE in p.fixes and p.still_open == () and p.new == () and p.answered is True and p.attempts == 1
    assert GOOD_TEXT in p.after.doc.text and "C4" not in {r.id for r in p.after.extraction.policy.rules}
    vocabulary, only, _ = extractor.calls[0]
    assert vocabulary == POLICY and only == (Anchor("Couriers", GOOD_TEXT),)
    consistent(p)


def test_a_change_that_breaks_an_example_is_retried():
    drafter = Drafter([Success((Remove(S6),)), Success(GOOD_EDIT)])
    p = run(propose(state([POST_LOST]), BEFORE, (LATE,), Choose("refund"), drafter=drafter,
                    extractor=Extractor([Success(GOOD_PART)]))).unwrap()
    assert p.attempts == 2 and p.broken == ()
    assert drafter.failures[0] is None and "post-lost" in (drafter.failures[1] or "")
    consistent(p)


def test_the_best_attempt_is_returned_when_none_is_clean():
    drafter = Drafter([Success(GOOD_EDIT)])
    p = run(propose(state(), BEFORE, (LATE,), Choose("refund"), drafter=drafter,
                    extractor=Extractor([Success(BAD_PART)]))).unwrap()
    assert p.new and p.attempts == 3 and len(drafter.failures) == 3
    consistent(p)


def test_a_misquoted_sentence_is_retried_then_reported():
    drafter = Drafter([Success((Replace(Anchor("Couriers", "Pets travel free on Tuesdays."), "x."),))])
    result = run(propose(state(), BEFORE, (LATE,), Choose("refund"), drafter=drafter, extractor=Extractor([])))
    assert isinstance(result, Failure) and isinstance(result.failure(), EditFailed)
    assert "Pets travel free" in result.failure().message and len(drafter.failures) == 3
    assert "Pets travel free" in (drafter.failures[1] or "")


def test_an_unmergeable_extraction_is_retried():
    unknown = part(When("x", Var("refnd"), Var("refund")), GOOD_TEXT)
    drafter = Drafter([Success(GOOD_EDIT)])
    p = run(propose(state(), BEFORE, (LATE,), Choose("refund"), drafter=drafter,
                    extractor=Extractor([Success(unknown), Success(GOOD_PART)]))).unwrap()
    assert p.attempts == 2 and "refnd" in (drafter.failures[1] or "")


def test_reword_skips_the_drafter():
    p = run(reword(state(), BEFORE, (LATE,), GOOD_EDIT, extractor=Extractor([Success(GOOD_PART)]))).unwrap()
    assert LATE in p.fixes and p.attempts == 1 and p.answered is None


def test_approve_saves_examples():
    p = run(propose(state(), BEFORE, (LATE,), Choose("refund"), drafter=Drafter([Success(GOOD_EDIT)]),
                    extractor=Extractor([Success(GOOD_PART)]))).unwrap()
    approved = approve(state(), p, BEFORE, {LATE: "refund"}).unwrap()
    [example] = approved.examples
    assert example.outcome == "refund" and holds(compile(approved.extraction.policy), example)
    assert approved.doc == p.after.doc


def test_llm_errors_stop_at_once():
    drafter = Drafter([Failure(Unavailable("down"))])
    result = run(propose(state(), BEFORE, (LATE,), Choose("refund"), drafter=drafter, extractor=Extractor([])))
    assert result == Failure(Unavailable("down")) and len(drafter.failures) == 1


def test_a_quote_missing_its_period_still_replaces_the_rule():
    """C2: the document is edited through a near-verbatim quote, so the rule of the sentence really replaced goes."""
    misquoted = Replace(Anchor(S4.section, S4.text.removesuffix(".")), GOOD_TEXT)
    p = run(propose(state(), BEFORE, (LATE,), Choose("refund"), drafter=Drafter([Success((misquoted,))]),
                    extractor=Extractor([Success(GOOD_PART)]))).unwrap()
    assert p.attempts == 1 and LATE in p.fixes and p.still_open == ()
    assert "C4" not in {r.id for r in p.after.extraction.policy.rules}
    assert all(link.anchor != S4 for link in p.after.extraction.links)


def test_a_replacement_without_a_period_is_extracted_not_dropped():
    """C1: the replaced sentence keeps its full stop, its neighbour keeps its rule, and the new text is extracted."""
    text = "A late courier parcel is refunded when the customer asks"
    extractor = Extractor([Success(part(When("x", And((COURIER, LATE_ASKED)), Var("refund")), text + "."))])
    p = run(reword(state(), BEFORE, (LATE,), (Replace(S5, text),), extractor=extractor)).unwrap()
    _, only, _ = extractor.calls[0]
    assert only == (Anchor("Couriers", text + "."),)
    rules = {r.id for r in p.after.extraction.policy.rules}
    assert "C5" not in rules and "C6" in rules


def insured_proposal():
    """The gap in gap.yaml (a parcel that isn't late) closed by a new question: was it insured?"""
    from policyproof.authoring.document import Insert
    from policyproof.authoring.ports import Describe
    from policyproof.core.syntax import Ask, BoolSort, Outcome, Variable

    gap_policy = load("defects/gap.yaml")
    doc = parse("## Late parcels\n\nLate parcels get a refund.\n")
    draft = Draft(doc, Extraction(gap_policy, (Link("G1", doc.sentences[0].anchor),), ()), ())
    before = problems(compile(gap_policy))
    text = "A parcel that isn't late is refunded only if it was insured."
    insured = Variable("insured", BoolSort(), Ask("Was the parcel insured?"), "The parcel was insured.")
    new = CheckedPolicy(replace(gap_policy, variables=(*gap_policy.variables, insured),
                                outcomes=(*gap_policy.outcomes, Outcome("nothing", (("refund", BoolLit(False)),))),
                                rules=(When("a", And((Not(Var("late")), Var("insured"))), Var("refund")),
                                       When("b", And((Not(Var("late")), Not(Var("insured")))), Not(Var("refund"))))))
    extractor = Extractor([Success(Extraction(new, (Link("a", Anchor("Late parcels", text)),
                                                    Link("b", Anchor("Late parcels", text))), ()))])
    p = run(propose(draft, before, (0,), Describe("it depends on whether it was insured"),
                    drafter=Drafter([Success((Insert("Late parcels", None, text),))]), extractor=extractor)).unwrap()
    return draft, before, p


def test_a_gap_closed_by_a_new_question_counts_as_fixed():
    """I1: the natural answer to a gap is often a new question; the old customer doesn't say, so judge every answer."""
    _, _, p = insured_proposal()
    assert p.still_open == () and p.fixes == (0,) and p.new == () and p.attempts == 1
    assert [v.name for v in p.additions.variables] == ["insured"]


def test_approve_completes_a_customer_the_fix_asks_more_of():
    """I4: the saved example must decide its outcome, so a new question gets an answer that proves it."""
    draft, before, p = insured_proposal()
    approved = approve(draft, p, before, {0: "refund"}).unwrap()
    [example] = approved.examples
    assert dict(example.customer)["insured"] == BoolLit(True)
    assert holds(compile(approved.extraction.policy), example)


def test_approve_refuses_an_answer_the_policy_cant_give():
    draft, before, p = insured_proposal()
    assert isinstance(approve(draft, p, before, {0: "jackpot"}), Failure)


def test_a_group_answered_per_customer_is_checked_per_customer():
    def ask(expect):
        drafter, extractor = Drafter([Success(GOOD_EDIT)]), Extractor([Success(GOOD_PART)])
        return run(propose(state(), BEFORE, (LATE,), Describe("each their own"), drafter=drafter,
                           extractor=extractor, retries=0, expect=expect)).unwrap()
    assert ask({LATE: "refund"}).answered is True
    assert ask({LATE: "nothing"}).answered is False
    assert ask(None).answered is None


def test_extra_rules_reach_the_situation():
    drafter, extractor = Drafter([Success(GOOD_EDIT)]), Extractor([Success(GOOD_PART)])
    run(propose(state(), BEFORE, (), Describe("post parcels"), drafter=drafter, extractor=extractor, rules=("C10",)))
    assert drafter.situations[0].sentences == (S10,)


def test_extract_again_merges_a_sentence_that_decides():
    base = Extraction(CheckedPolicy(replace(POLICY, rules=tuple(r for r in POLICY.rules if r.id != "C10"))),
                      tuple(link for link in BASE.links if link.rule != "C10"), (S10,))
    post = When("x", And((Cmp("eq", Var("carrier"), EnumLit("Carrier", "POST")), Not(Var("lost")))), Not(Var("refund")))
    found = Extraction(CheckedPolicy(replace(POLICY, rules=(post,))), (Link("x", S10),), ())
    extractor = Extractor([Success(found)])
    before = problems(compile(base.policy))
    p = run(extract_again(Draft(DOC, base, ()), before, (S10,), guidance="it decides", extractor=extractor)).unwrap()
    assert p.after.doc == DOC and p.after.extraction.uncovered == ()
    assert any(link.anchor == S10 for link in p.after.extraction.links)
    assert extractor.calls == [(base.policy, (S10,), "it decides")]
