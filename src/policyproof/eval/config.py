"""Reader configurations from a YAML file: named models (pydantic-ai model strings) and, for each configuration, which
model reads answers, facts and claims and which rewrites, alone or two at a time (`agree`, `union`).

The whole file is checked before any model is built; building creates one reader per model and needs the `[llm]`
extra (and `[jev]` for `typesafe:` models).
"""
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import yaml
from pydantic_ai.models import Model, infer_model
from returns.result import Failure, Result, Success

from policyproof.core._result import sequence
from policyproof.effects.consensus import AgreeingAnswers, AgreeingFacts, UnionClaims
from policyproof.effects.llm.readers import LLMReaders
from policyproof.effects.ports import AnswerReader, ClaimReader, FactReader
from policyproof.eval.run import Configuration

if TYPE_CHECKING:
    from policyproof.effects.jev.readers import JevReaders

JEV_PREFIX = "typesafe:"


@dataclass(frozen=True, slots=True)
class Use:
    model: str


@dataclass(frozen=True, slots=True)
class Agree:
    a: str
    b: str


@dataclass(frozen=True, slots=True)
class UnionOf:
    a: str
    b: str


type Slot = Use | Agree | UnionOf


@dataclass(frozen=True, slots=True)
class ConfigSpec:
    name: str
    answers: Use | Agree
    facts: Use | Agree
    claims: Use | UnionOf
    rewriter: Use
    min_confidence: float = 0.5
    firm_confidence: float = 0.8


@dataclass(frozen=True, slots=True)
class ConfigFile:
    models: Mapping[str, str]
    configurations: tuple[ConfigSpec, ...]


@dataclass(frozen=True, slots=True)
class ConfigError:
    path: str
    message: str

    def __str__(self) -> str:
        return f"{self.path or '<root>'}: {self.message}"


def _err[T](path: str, message: str) -> Result[T, ConfigError]:
    return Failure(ConfigError(path, message))


def _slot(models: Mapping[str, str], x: object, path: str, kind: str) -> Result[Slot, ConfigError]:
    def model(name: object, where: str) -> Result[str, ConfigError]:
        if not isinstance(name, str) or name not in models:
            return _err(where, f"unknown model {name!r} (models: {', '.join(models)})")
        if kind in ("claims", "rewriter") and models[name].startswith(JEV_PREFIX):
            return _err(where, "Jev reads only answers and facts; use a chat model here")
        return Success(name)

    match x:
        case str():
            return model(x, path).map(Use)
        case {"agree": [a, b]} if len(x) == 1:
            if kind not in ("answers", "facts"):
                return _err(path, "claims combine with union; a rewriter is one model" if kind == "claims"
                            else "a rewriter is one model")
            return model(a, path).bind(lambda m1: model(b, path).map(lambda m2: Agree(m1, m2)))
        case {"union": [a, b]} if len(x) == 1:
            if kind != "claims":
                return _err(path, "answers and facts combine with agree" if kind in ("answers", "facts")
                            else "a rewriter is one model")
            return model(a, path).bind(lambda m1: model(b, path).map(lambda m2: UnionOf(m1, m2)))
        case _:
            return _err(path, "expected a model name, {agree: [a, b]} or {union: [a, b]}")


def _confidence(x: object, path: str, default: float) -> Result[float, ConfigError]:
    if x is None:
        return Success(default)
    if isinstance(x, int | float) and not isinstance(x, bool) and 0 <= x <= 1:
        return Success(float(x))
    return _err(path, "a confidence is a number between 0 and 1")


def _spec_of(name: str, a: Slot, f: Slot, c: Slot, r: Slot, lo: float, hi: float) -> ConfigSpec:
    """`_slot` has already refused `union` for answers and facts, `agree` for claims, and both for the rewriter."""
    assert not isinstance(a, UnionOf) and not isinstance(f, UnionOf) and not isinstance(c, Agree)
    assert isinstance(r, Use)
    return ConfigSpec(name, a, f, c, r, lo, hi)


def _spec(models: Mapping[str, str], name: str, x: object, path: str) -> Result[ConfigSpec, ConfigError]:
    keys = {"answers", "facts", "claims", "rewriter", "min_confidence", "firm_confidence"}
    if not isinstance(x, dict):
        return _err(path, "expected a map")
    extra = [k for k in x if k not in keys]
    if extra:
        return _err(f"{path}.{extra[0]}", f"unknown key {extra[0]!r}")
    missing = sorted({"answers", "facts", "claims", "rewriter"} - x.keys())
    if missing:
        return _err(path, f"missing required key {missing[0]!r}")

    def slot(k: str) -> Result[Slot, ConfigError]:
        return _slot(models, x[k], f"{path}.{k}", k)

    return slot("answers").bind(lambda a: slot("facts").bind(lambda f: slot("claims").bind(lambda c: slot(
        "rewriter").bind(lambda r: _confidence(x.get("min_confidence"), f"{path}.min_confidence", 0.5).bind(
            lambda lo: _confidence(x.get("firm_confidence"), f"{path}.firm_confidence", 0.8).map(
                lambda hi: _spec_of(name, a, f, c, r, lo, hi)))))))


def decode_config(data: object) -> Result[ConfigFile, ConfigError]:
    if not isinstance(data, dict) or set(data) != {"models", "configurations"}:
        return _err("", "expected a map with exactly the keys models and configurations")
    models, configs = data["models"], data["configurations"]
    if not isinstance(models, dict) or not isinstance(configs, dict):
        return _err("", "models and configurations are maps")
    for k, v in models.items():
        if not isinstance(v, str):
            return _err(f"models.{k}", "expected a pydantic-ai model string, e.g. bedrock:<model id>")
    return sequence(_spec(models, str(k), v, f"configurations.{k}") for k, v in configs.items()).map(
        lambda specs: ConfigFile(dict(models), specs))


def load_config(path: Path) -> Result[ConfigFile, ConfigError]:
    try:
        data = yaml.safe_load(path.read_text())
    except OSError as e:
        return _err("", f"can't read {path}: {e.strerror}")
    except yaml.YAMLError as e:
        return _err("", f"invalid YAML: {e}")
    return decode_config(data)


def _is_jev(m: Model) -> bool:
    try:
        from pydantic_ai.models.typesafe import TypeSafeModel
    except ImportError:
        return False
    return isinstance(m, TypeSafeModel)


def _jev_reader(m: Model) -> "JevReaders":
    from policyproof.effects.jev.readers import JevReaders  # imported only when a Jev model is used: needs [jev]
    return JevReaders(m)


def build(cf: ConfigFile, models: Mapping[str, Model] | None = None) -> Result[tuple[Configuration, ...], ConfigError]:
    """The configurations, with one reader per model they use (models no configuration uses aren't built).
    `models` replaces model strings (tests pass FunctionModels)."""
    chat: dict[str, LLMReaders] = {}
    jev: dict[str, JevReaders] = {}
    used = {m for s in cf.configurations for slot in (s.answers, s.facts, s.claims, s.rewriter)
            for m in ((slot.model,) if isinstance(slot, Use) else (slot.a, slot.b))}
    for name, spec in cf.models.items():
        if name not in used:
            continue
        try:
            m = models[name] if models is not None and name in models else infer_model(spec)
        except Exception as e:
            return _err(f"models.{name}", f"can't build {spec!r}: {e}")
        if _is_jev(m):
            jev[name] = _jev_reader(m)
        else:
            chat[name] = LLMReaders(m)

    def reads(name: str) -> "LLMReaders | JevReaders":
        return chat[name] if name in chat else jev[name]

    def answers(s: Use | Agree) -> AnswerReader:
        return reads(s.model) if isinstance(s, Use) else AgreeingAnswers(reads(s.a), reads(s.b))

    def facts(s: Use | Agree) -> FactReader:
        return reads(s.model) if isinstance(s, Use) else AgreeingFacts(reads(s.a), reads(s.b))

    built: list[Configuration] = []
    for s in cf.configurations:
        writers = [s.claims.model] if isinstance(s.claims, Use) else [s.claims.a, s.claims.b]
        for name in [*writers, s.rewriter.model]:
            if name not in chat:
                return _err(f"configurations.{s.name}", f"{name} is a Jev model; Jev reads only answers and facts")
        claims: ClaimReader = (chat[s.claims.model] if isinstance(s.claims, Use)
                               else UnionClaims(chat[s.claims.a], chat[s.claims.b]))
        built.append(Configuration(s.name, answers(s.answers), facts(s.facts), claims, chat[s.rewriter.model],
                                   s.min_confidence, s.firm_confidence))
    return Success(tuple(built))
