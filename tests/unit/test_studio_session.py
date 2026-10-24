"""The studio's operations on real files, with fake models: nothing is written unchecked, everything can be undone."""
import asyncio
from dataclasses import replace

from authoring_fakes import Drafter, Extractor, Phraser
from returns.result import Failure, Success
from studio_fixtures import EXTRACTION, INTRO, POLICY, S4, S5, S6, S9, S10, TEXT

from policyproof.authoring.document import Anchor, Replace
from policyproof.authoring.extraction import Extraction, Link
from policyproof.core.syntax import And, CheckedPolicy, Cmp, EnumLit, IntLit, Not, Var, When
from policyproof.effects.errors import Unavailable
from policyproof.studio import wire as w
from policyproof.studio.session import Ports, Session, Studio
from policyproof.studio.workspace import Files, Paths, Workspace, load, load_snapshot, save, save_snapshot

COURIER = Cmp("eq", Var("carrier"), EnumLit("Carrier", "COURIER"))
LATE_ASKED = And((Cmp("gt", Var("daysLate"), IntLit(0)), Var("asked")))
GOOD_TEXT = "Courier parcels are never refunded, unless they arrive late and the customer asks."
GOOD = Anchor("Couriers", GOOD_TEXT)


def part(rule: When) -> Extraction:
    return Extraction(CheckedPolicy(replace(POLICY, rules=(rule,))), (Link(rule.id, GOOD),), ())


GOOD_PART = part(When("x", And((COURIER, Not(LATE_ASKED))), Not(Var("refund"))))
BAD_PART = part(When("x", Var("asked"), Not(Var("refund"))))
FULL_AFTER_FIX = Extraction(POLICY, (Link("C4", GOOD), Link("C5", S5), Link("C6", S6), Link("C10", S10),
                                     Link("C9", S9)), (INTRO,))


def run(coro):
    return asyncio.run(coro)


GOOD_EDIT = (Replace(S4, GOOD_TEXT),)


def ports(extracted=(GOOD_PART,), edits=(GOOD_EDIT,)) -> Ports:
    return Ports(Extractor([Success(x) for x in extracted]), Drafter([Success(e) for e in edits]),
                 Phraser(Failure(Unavailable("off")), Failure(Unavailable("off"))))


def opened(tmp_path, p: Ports | None = None) -> Session:
    paths = Paths.of(tmp_path / "couriers.md")
    paths.doc.write_text(TEXT)
    save(paths, Files(TEXT, EXTRACTION, (), Workspace.empty(TEXT)))
    save_snapshot(paths, EXTRACTION)
    return run(Session.open(paths, p or ports())).unwrap()


def state(reply) -> w.SessionView:
    assert isinstance(reply, w.StateReply), reply
    return reply.state


def keys(s: Session) -> list[str]:
    return [i.key for i in s.view().state.items]


def proposal(s: Session, key="clash:C4+C5", option=0, text="") -> w.ProposalView:
    reply = run(s.answer(w.AnswerRequest(key, option, text)))
    assert isinstance(reply, w.ProposalReply), reply
    return reply.proposal


def test_open_shows_the_couriers_clashes(tmp_path):
    s = opened(tmp_path)
    view = s.view().state
    assert {"clash:C4+C5", "clash:C4+C6"} <= {i.key for i in view.items}
    assert [set(g) for g in view.groups] == [{"clash:C4+C5", "clash:C4+C6"}]
    assert view.model and not view.can_undo and not view.done and view.version == 0 and not view.outside


def test_answer_then_accept_writes_the_files_and_an_example(tmp_path):
    s = opened(tmp_path)
    p = proposal(s)
    assert p.changes == (w.Change("replace", "Couriers", S4.text, GOOD_TEXT),) and not p.risky
    assert any(c.tone == "ok" and c.text.startswith("Fixes") for c in p.checks)
    view = state(run(s.accept(w.AcceptRequest(p.id, ()))))
    assert GOOD_TEXT in s.paths.doc.read_text()
    files = load(s.paths).unwrap()
    assert files is not None and len(files.examples) == 1 and files.examples[0].outcome == "refund"
    assert "clash:C4+C5" not in {i.key for i in view.items}
    assert view.banner is not None and len(view.banner.fixed) == 1 and view.banner.changed == ("Rule 1",)
    assert view.can_undo and view.version == 1 and view.fixed == 1 and len(view.examples) == 1


def test_undo_restores_the_files(tmp_path):
    s = opened(tmp_path)
    run(s.accept(w.AcceptRequest(proposal(s).id, ())))
    view = state(run(s.undo()))
    assert s.paths.doc.read_text() == TEXT and view.examples == () and not view.can_undo
    assert "clash:C4+C5" in {i.key for i in view.items}


def test_undo_with_no_history_is_an_error(tmp_path):
    assert isinstance(run(opened(tmp_path).undo()), w.ErrorReply)


def test_accepting_a_stale_proposal_is_refused(tmp_path):
    s = opened(tmp_path)
    p = proposal(s)
    state(run(s.dismiss(w.DismissRequest("constraint:C9", "Exactly right"))))
    reply = run(s.accept(w.AcceptRequest(p.id, ())))
    assert isinstance(reply, w.ErrorReply)
    assert s.paths.doc.read_text() == TEXT


def test_accept_refuses_when_the_document_changed_on_disk(tmp_path):
    s = opened(tmp_path)
    p = proposal(s)
    s.paths.doc.write_text(TEXT + "\nA sentence from the author's editor.\n")
    assert s.outside().changed
    reply = run(s.accept(w.AcceptRequest(p.id, ())))
    assert isinstance(reply, w.ErrorReply) and "Extract again" in reply.message
    assert s.paths.doc.read_text().endswith("A sentence from the author's editor.\n")


def test_outside_ignores_the_studios_own_writes(tmp_path):
    s = opened(tmp_path)
    run(s.accept(w.AcceptRequest(proposal(s).id, ())))
    assert not s.outside().changed


def test_a_change_that_causes_a_new_problem_marks_it_new(tmp_path):
    s = opened(tmp_path, ports(extracted=(BAD_PART,)))
    p = proposal(s)
    assert p.risky and any(c.tone == "warn" for c in p.checks)
    view = state(run(s.accept(w.AcceptRequest(p.id, ()))))
    assert any(i.new for i in view.items) and view.banner is not None and view.banner.new


def test_dismiss_saves_the_reason(tmp_path):
    s = opened(tmp_path)
    view = state(run(s.dismiss(w.DismissRequest("constraint:C9", "Exactly right"))))
    assert "constraint:C9" not in {i.key for i in view.items}
    assert "Exactly right" in s.paths.workspace.read_text()


def test_a_reason_is_required_and_errors_cant_be_dismissed(tmp_path):
    s = opened(tmp_path)
    assert isinstance(run(s.dismiss(w.DismissRequest("constraint:C9", " "))), w.ErrorReply)
    assert isinstance(run(s.dismiss(w.DismissRequest("clash:C4+C5", "no"))), w.ErrorReply)


def test_background_hides_the_sentence(tmp_path):
    s = opened(tmp_path)
    key = next(k for k in keys(s) if k.startswith("uncovered:"))
    view = state(run(s.answer(w.AnswerRequest(key, 1, ""))))
    assert not any(i.kind == "uncovered" for i in view.items)
    assert view.doc.sections[0].sentences[0].state == "background"


def test_answers_need_a_model(tmp_path):
    s = opened(tmp_path, Ports())
    reply = run(s.answer(w.AnswerRequest("clash:C4+C5", 0, "")))
    assert isinstance(reply, w.ErrorReply) and "--model" in reply.message
    assert not s.view().state.model


def test_a_described_answer_needs_its_sentence(tmp_path):
    s = opened(tmp_path)
    item = next(i for i in s.view().state.items if i.key == "clash:C4+C5")
    depends = next(n for n, o in enumerate(item.options) if o.label.startswith("It depends"))
    assert isinstance(run(s.answer(w.AnswerRequest(item.key, depends, ""))), w.ErrorReply)
    assert proposal(s, option=depends, text="only when the parcel is late").id


def test_a_group_is_proposed_once(tmp_path):
    s = opened(tmp_path)
    reply = run(s.answer_group(w.GroupRequest((w.GroupAnswer("clash:C4+C5", 0, ""),
                                                w.GroupAnswer("clash:C4+C6", 0, "")))))
    assert isinstance(reply, w.ProposalReply)
    drafter = s.ports.drafter
    assert isinstance(drafter, Drafter) and len(drafter.answers) >= 1
    assert drafter.answers[0].__class__.__name__ == "Describe"


def test_reword_checks_the_authors_wording(tmp_path):
    s = opened(tmp_path, ports(extracted=(GOOD_PART, GOOD_PART)))
    p = proposal(s)
    reply = run(s.reword(w.RewordRequest(p.id, (GOOD_TEXT,))))
    assert isinstance(reply, w.ProposalReply) and reply.proposal.id != p.id
    state(run(s.accept(w.AcceptRequest(reply.proposal.id, ()))))


def test_extract_again_then_resolve_keeps_the_authors_fix(tmp_path):
    s = opened(tmp_path, ports(extracted=(GOOD_PART, FULL_AFTER_FIX)))
    run(s.accept(w.AcceptRequest(proposal(s).id, ())))
    reply = run(s.extract_again())
    assert isinstance(reply, w.ReextractReply)
    (diff,) = reply.reextract.diffs
    assert diff.sentence == GOOD_TEXT and diff.hand_fixed and diff.keep == "mine"
    view = state(run(s.resolve(w.ResolveRequest(reply.reextract.id, ("mine",)))))
    assert "clash:C4+C5" not in {i.key for i in view.items}
    assert load_snapshot(s.paths) == FULL_AFTER_FIX


def test_open_without_a_policy_extracts(tmp_path):
    paths = Paths.of(tmp_path / "couriers.md")
    paths.doc.write_text(TEXT)
    s = run(Session.open(paths, ports(extracted=(EXTRACTION,)))).unwrap()
    assert paths.policy.exists() and load_snapshot(paths) == EXTRACTION and s.view().state.items


def test_open_without_a_policy_or_a_model_is_an_error(tmp_path):
    paths = Paths.of(tmp_path / "couriers.md")
    paths.doc.write_text(TEXT)
    got = run(Session.open(paths, Ports()))
    assert isinstance(got, Failure) and "--model" in got.failure()


def test_the_studio_opens_a_pasted_document(tmp_path):
    studio = Studio(tmp_path, ports(extracted=(EXTRACTION,)))
    assert isinstance(studio.state(), w.StartReply)
    reply = run(studio.start(w.StartRequest(None, "couriers", TEXT)))
    assert isinstance(reply, w.StateReply) and (tmp_path / "couriers.md").read_text() == TEXT
    again = run(studio.start(w.StartRequest(None, "couriers", TEXT)))
    assert isinstance(again, w.ErrorReply)


LOST_TEXT = "Courier parcels are never refunded, unless they are lost."
LOST_PART = Extraction(CheckedPolicy(replace(POLICY, rules=(When("x", And((COURIER, Not(Var("lost")))),
                                                                  Not(Var("refund"))),))),
                       (Link("x", Anchor("Couriers", LOST_TEXT)),), ())


def test_a_problem_that_was_already_there_is_not_new(tmp_path):
    s = opened(tmp_path, ports(extracted=(LOST_PART,), edits=((Replace(S4, LOST_TEXT),),)))
    view = state(run(s.accept(w.AcceptRequest(proposal(s, key="clash:C4+C6").id, ()))))
    late = [i for i in view.items if i.kind == "clash"]
    assert late and not any(i.new for i in late)  # the late-courier clash was there before, under another rule id
    assert view.banner is not None and view.banner.new == ()
