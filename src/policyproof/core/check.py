"""The answer check: is everything a reply claims proven by the policy and the facts, and does the reply do what the
decision requires? Claims arrive already translated (by a translator in `policyproof.effects`); this module only
judges them.

A reply rule is a plain function from the check's input to the problems it finds. The built-in rules are generic;
domain rules (forbidden offers, required source mentions, allowed flight numbers) are made with `forbid`,
`require_mention` and `only_entities`.
"""
from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Literal, assert_never

from policyproof.core.decide import Decided, Decision, NeedInfo, fact_assertions, firm_facts, outcome_expr
from policyproof.core.facts import Facts
from policyproof.core.prove import Contingent, Inconsistent, Proven, Refuted, Undetermined, classify, entails
from policyproof.core.solver import Compiled
from policyproof.core.syntax import Expr

type ClaimStatus = Literal["proven", "contradicts", "not_proven", "inconsistent", "ungrounded"]


@dataclass(frozen=True, slots=True)
class Claim:
    expr: Expr
    quote: str  # the words in the reply the claim was read from


@dataclass(frozen=True, slots=True)
class ClaimResult:
    claim: Claim
    status: ClaimStatus


@dataclass(frozen=True, slots=True)
class Problem:
    rule: str
    message: str


@dataclass(frozen=True, slots=True)
class CheckInput:
    compiled: Compiled
    decision: Decision
    facts: Facts
    reply: str
    claims: tuple[ClaimResult, ...]


@dataclass(frozen=True, slots=True)
class CheckResult:
    passed: bool
    claims: tuple[ClaimResult, ...]
    problems: tuple[Problem, ...]


type ReplyRule = Callable[[CheckInput], tuple[Problem, ...]]


def normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def judge_claims(c: Compiled, fs: Facts, reply: str, claims: Sequence[Claim]) -> tuple[ClaimResult, ...]:
    """Each claim's status against the rules and the firm facts. A claim whose quote isn't in the reply is
    'ungrounded': the translator invented it, so it is reported but not held against the reply."""
    text, given = normalize(reply), fact_assertions(firm_facts(c, fs))

    def status(claim: Claim) -> ClaimStatus:
        if not claim.quote.strip() or normalize(claim.quote) not in text:
            return "ungrounded"
        verdict = classify(c, claim.expr, given)
        match verdict:
            case Proven():
                return "proven"
            case Refuted():
                return "contradicts"
            case Contingent() | Undetermined():
                return "not_proven"
            case Inconsistent():
                return "inconsistent"
            case _:
                assert_never(verdict)

    return tuple(ClaimResult(claim, status(claim)) for claim in claims)


# ---- built-in rules


def claims_hold(i: CheckInput) -> tuple[Problem, ...]:
    words = {"contradicts": "contradicts the policy and the facts",
             "not_proven": "is not proven: nothing in the decision supports it",
             "inconsistent": "rests on facts that contradict each other"}
    return tuple(Problem("claims_hold", f'"{r.claim.quote}" {words[r.status]}.')
                 for r in i.claims if r.status in words)


def states_outcome(i: CheckInput) -> tuple[Problem, ...]:
    if not isinstance(i.decision, Decided):
        return ()
    name = i.decision.outcome
    goal = outcome_expr(next(o for o in i.compiled.policy.outcomes if o.name == name))
    if any(r.status == "proven" and entails(i.compiled, [r.claim.expr], goal) for r in i.claims):
        return ()
    return (Problem("states_outcome", f"The reply must clearly state the outcome ({name.replace('_', ' ')})."),)


def asks_open_question(i: CheckInput) -> tuple[Problem, ...]:
    """The answer is read against the exact question, so it must be asked word for word, and last."""
    if not isinstance(i.decision, NeedInfo):
        return ()
    question, text = normalize(i.decision.question), normalize(i.reply)
    if question not in text:
        return (Problem("asks_open_question", f'Ask the open question exactly as written: "{i.decision.question}"'),)
    if not text.endswith(question):
        return (Problem("asks_open_question", "The open question must be the last thing in the reply."),)
    return ()


def single_question(i: CheckInput) -> tuple[Problem, ...]:
    """A yes/no answer is only unambiguous if the question isn't "A, or B?"."""
    if not isinstance(i.decision, NeedInfo):
        return ()
    questions = re.findall(r"[^.?!]*\?", i.reply)
    if any(re.search(r"\bor\b", q, re.IGNORECASE) for q in questions):
        return (Problem("single_question", "Ask one yes/no question, not an either/or question."),)
    return ()


DEFAULT_RULES: tuple[ReplyRule, ...] = (claims_hold, states_outcome, asks_open_question, single_question)

# ---- rule builders for domain checks


def forbid(pattern: str, message: str) -> ReplyRule:
    """A problem whenever `pattern` occurs (case-insensitive), e.g. offers the policy never makes."""
    def rule(i: CheckInput) -> tuple[Problem, ...]:
        found = sorted({m.group(0).lower() for m in re.finditer(pattern, i.reply, re.IGNORECASE)})
        return (Problem("forbid", f"{message}: {', '.join(found)}"),) if found else ()
    return rule


def require_mention(pattern: str, message: str) -> ReplyRule:
    """Once decided, the reply must mention `pattern` (e.g. where the facts came from)."""
    def rule(i: CheckInput) -> tuple[Problem, ...]:
        decided = isinstance(i.decision, Decided)
        return (Problem("require_mention", message),) if decided and not re.search(pattern, i.reply, re.I) else ()
    return rule


def only_entities(pattern: str, allowed: frozenset[str], message: str) -> ReplyRule:
    """Every match of `pattern` must be in `allowed` (e.g. only flight numbers the schedule returned)."""
    def rule(i: CheckInput) -> tuple[Problem, ...]:
        extra = sorted(set(re.findall(pattern, i.reply)) - allowed)
        return (Problem("only_entities", f"{message}: {', '.join(extra)}"),) if extra else ()
    return rule


def check_reply(c: Compiled, decision: Decision, fs: Facts, reply: str, claims: Sequence[Claim],
                rules: Sequence[ReplyRule] = DEFAULT_RULES) -> CheckResult:
    judged = judge_claims(c, fs, reply, claims)
    i = CheckInput(c, decision, fs, reply, judged)
    problems = tuple(p for rule in rules for p in rule(i))
    return CheckResult(not problems, judged, problems)
