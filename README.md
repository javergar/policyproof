# policyproof

Prove what an agent may decide and say, from a written policy.

A policy is a YAML file: enum sorts, typed variables (from a system, asked of the customer, or derived), rules as
expression trees, and named outcomes. `policyproof` checks the policy is sound, decides cases with the Z3 solver
(or picks the one question that settles them), and checks every claim in an agent's reply against the proof.

```python
from policyproof.core.codec import from_yaml
from policyproof.core.decide import decide
from policyproof.core.facts import Fact, FromSystem, facts
from policyproof.core.solver import compile
from policyproof.core.syntax import IntLit
from policyproof.core.validate import gate

policy = from_yaml(open("policy.yaml").read()).unwrap()
compiled = gate(compile(policy)).unwrap()          # fails on any validation error
decision = decide(compiled, facts(Fact("daysLate", IntLit(3), FromSystem("tracking"))))
```

The core (`policyproof.core`) is pure and deterministic: no LLMs, no network, no I/O. Translating customer text into
facts, and replies into claims, belongs to `policyproof.effects` (later milestones), behind protocols, with any LLM
provider or the Jev translator.

## Development

```bash
uv sync
uv run ruff check . && uv run ty check && uv run lint-imports && uv run pytest
uv run pytest --hypothesis-profile=ci     # the laws with 1000 examples each (about 8 minutes)
uv run python -m policyproof.schema       # regenerate policy.schema.json after changing the schema builder
```

Licensed under Apache-2.0.
