import sys
from pathlib import Path

import pytest
from hypothesis import settings
from returns.pipeline import is_successful

from policyproof.core.codec import from_yaml
from policyproof.core.syntax import CheckedPolicy

sys.path.insert(0, str(Path(__file__).parent))  # so tests can `import strategies`

POLICIES = Path(__file__).parent / "policies"
settings.register_profile("default", max_examples=200, deadline=None)
settings.register_profile("ci", max_examples=1000, deadline=None)
settings.load_profile("default")


def load(name: str) -> CheckedPolicy:
    result = from_yaml((POLICIES / name).read_text())
    if not is_successful(result):
        raise AssertionError(f"{name}: {result.failure()}")
    return result.unwrap()


@pytest.fixture(scope="session")
def toy() -> CheckedPolicy:
    return load("toy.yaml")
