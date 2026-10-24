"""What an extraction is: a policy, the links from its rules to the document's sentences, and the sentences no rule
came from. Pure, so merging and the studio's workspace can use it without the ports' error types."""
from __future__ import annotations

from dataclasses import dataclass

from policyproof.authoring.document import Anchor
from policyproof.core.syntax import CheckedPolicy


@dataclass(frozen=True, slots=True)
class Link:
    rule: str
    anchor: Anchor


@dataclass(frozen=True, slots=True)
class Extraction:
    policy: CheckedPolicy
    links: tuple[Link, ...]  # every rule has at least one link, unless it was added by hand in the YAML
    uncovered: tuple[Anchor, ...]  # sentences no rule came from
