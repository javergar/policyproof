"""The instructions the authoring models get. Pure functions of their inputs, so they are tested as snapshots."""
from __future__ import annotations

from policyproof.authoring.document import Anchor, Document
from policyproof.core.syntax import Ask, CheckedPolicy, Derived, System
from policyproof.effects.llm.prompts import value_text, values_of

FORMAT = """\
How to write the policy:
- sorts: a choice between named values, e.g. {"name": "Carrier", "values": ["POST", "COURIER"]}.
- variables: every fact a rule uses. Each has a name (letters and digits, camelCase), a sort (Bool, Int, Real or a \
sort's name), a role and a description of what it means, literally.
  - role "system": the business's own systems know it (orders, tracking, payments). Never asked.
  - role "ask": only the customer can say. Give the question the agent asks, in plain words.
  - role "derived": decided by the rules, e.g. whether the customer gets a refund.
  - display: how an author reads each value. For Bool and choice variables, a phrase per value \
({"true": "Asked for a refund", "false": "Didn't ask for a refund"}); for numbers, text with one {} \
("{} days late").
- rules: each cites the number of the sentence it comes from. A sentence may give several rules.
  - kind "when": when `when` holds, `then` holds. Most sentences are this.
  - kind "define": `var` holds exactly when `as` holds. Only when the sentence really says "only if" or "means".
  - kind "constraint": a fact about the world that always holds, e.g. days late is never negative.
- Expressions: a variable's name; true/false, numbers, or a choice value's name; {"not": e}; {"and": [e, ...]}; \
{"or": [e, ...]}; {"implies": [a, b]}; {"iff": [a, b]}; {"eq": [a, b]} and likewise ne, lt, le, gt, ge; \
{"add": [...]}, {"sub": [a, b]}, {"mul": [...]}; {"in": [e, [value, ...]]}; reals as {"real": "2.5"}.
- outcomes: what a customer can end up with, each a name, an assignment of derived variables to values, and a \
display ("A refund"). Give an outcome for every result the document describes, including getting nothing.
- Only state what a sentence says. Don't infer a fact the document doesn't state.
- A sentence that doesn't decide what a customer gets (a promise about timing, a greeting, background) is background: \
extract nothing from it.\
"""


def _numbered(doc: Document) -> dict[Anchor, int]:
    return {s.anchor: i for i, s in enumerate(doc.sentences, start=1)}


def _document(doc: Document) -> str:
    lines: list[str] = []
    section: str | None = None
    for i, s in enumerate(doc.sentences, start=1):
        if s.anchor.section != section:
            section = s.anchor.section
            lines.append(f"\n## {section}" if section else "")
        lines.append(f"{i}. {s.anchor.text}")
    return "\n".join(lines).strip("\n")


def _vocabulary(p: CheckedPolicy) -> str:
    lines = ["Use these names. Add a name only when a sentence needs one the list doesn't have, and keep every name "
             "below in your answer, unchanged:"]
    lines += [f"- sort {s.name}: {', '.join(s.values)}" for s in p.sorts]
    for v in p.variables:
        match v.role:
            case System():
                role = "system"
            case Ask(question):
                role = f'ask, "{question}"'
            case Derived():
                role = "derived"
        lines.append(f"- {v.name} ({values_of(v.sort)}; {role}): {v.description}")
    for o in p.outcomes:
        assignment = ", ".join(f"{var} = {value_text(x)}" for var, x in o.assignment)
        lines.append(f"- outcome {o.name}: {assignment}")
    return "\n".join(lines)


def extraction_prompt(doc: Document, vocabulary: CheckedPolicy | None, only: tuple[Anchor, ...] | None,
                      guidance: str) -> str:
    numbers = _numbered(doc)
    parts = ["You turn a business policy, written for people, into rules a solver can check. The whole document is "
             "below, every sentence numbered, under its heading.", _document(doc), FORMAT]
    if vocabulary is not None:
        parts.append(_vocabulary(vocabulary))
    if only is not None:
        listed = sorted(numbers[a] for a in only if a in numbers)
        parts.append("Extract rules only from sentences " + ", ".join(map(str, listed)) + ". Read the rest of the "
                     "document for context, but give no rules for it.")
    if guidance.strip():
        parts.append(f"The policy's author adds: {guidance.strip()}")
    return "\n\n".join(parts)
