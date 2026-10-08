import pytest
from pydantic_ai.models.test import TestModel
from pydantic_ai.models.typesafe import TypeSafeModel
from pydantic_ai.providers.typesafe import TypeSafeProvider
from returns.result import Failure
from typesafe_sdk import AsyncTypeSafeClient

from policyproof.effects.consensus import AgreeingAnswers, AgreeingFacts, UnionClaims
from policyproof.effects.jev.readers import JevReaders
from policyproof.effects.llm.readers import LLMReaders
from policyproof.eval.config import Agree, ConfigSpec, UnionOf, Use, build, decode_config, load_config

DATA = {
    "models": {"haiku": "test", "sonnet": "test", "jev": "typesafe:jev-1.13.0"},
    "configurations": {
        "haiku-only": {"answers": "haiku", "facts": "haiku", "claims": "haiku", "rewriter": "haiku"},
        "jev-plus-haiku": {"answers": {"agree": ["jev", "haiku"]}, "facts": {"agree": ["jev", "haiku"]},
                           "claims": {"union": ["haiku", "sonnet"]}, "rewriter": "haiku",
                           "min_confidence": 0.6, "firm_confidence": 0.9},
    },
}


def jev_model() -> TypeSafeModel:
    return TypeSafeModel("jev-1.13.0", provider=TypeSafeProvider(typesafe_client=AsyncTypeSafeClient(api_key="x")))


def test_a_config_file_decodes():
    cf = decode_config(DATA).unwrap()
    assert cf.configurations[1] == ConfigSpec("jev-plus-haiku", Agree("jev", "haiku"), Agree("jev", "haiku"),
                                              UnionOf("haiku", "sonnet"), Use("haiku"), 0.6, 0.9)
    assert cf.configurations[0].min_confidence == 0.5 and cf.configurations[0].firm_confidence == 0.8


def test_build_makes_one_reader_per_model_and_combines_them():
    haiku = TestModel()
    built = build(decode_config(DATA).unwrap(), {"haiku": haiku, "sonnet": TestModel(), "jev": jev_model()}).unwrap()
    plain, mixed = built
    assert plain.name == "haiku-only" and isinstance(plain.answers, LLMReaders) and plain.answers.model is haiku
    assert plain.answers is plain.facts is plain.claims is plain.rewriter  # one reader per model
    assert isinstance(mixed.answers, AgreeingAnswers) and isinstance(mixed.answers.a, JevReaders)
    assert isinstance(mixed.facts, AgreeingFacts) and isinstance(mixed.claims, UnionClaims)
    assert (mixed.min_confidence, mixed.firm_confidence) == (0.6, 0.9)


def test_build_infers_models_from_their_strings():
    data = {"models": {"t": "test"}, "configurations": {"x": {"answers": "t", "facts": "t", "claims": "t",
                                                              "rewriter": "t"}}}
    [cfg] = build(decode_config(data).unwrap()).unwrap()
    assert isinstance(cfg.answers, LLMReaders) and isinstance(cfg.answers.model, TestModel)


def test_an_unknown_model_provider_is_a_config_error():
    data = {"models": {"t": "nosuchprovider:x"}, "configurations": {
        "x": {"answers": "t", "facts": "t", "claims": "t", "rewriter": "t"}}}
    got = build(decode_config(data).unwrap())
    assert isinstance(got, Failure) and got.failure().path == "models.t"


@pytest.mark.parametrize(("change", "path", "message"), [
    (lambda d: d["configurations"]["haiku-only"].update(answers="gpt"), "configurations.haiku-only.answers",
     "unknown model 'gpt'"),
    (lambda d: d["configurations"]["haiku-only"].update(claims="jev"), "configurations.haiku-only.claims",
     "Jev reads only answers and facts"),
    (lambda d: d["configurations"]["haiku-only"].update(rewriter="jev"), "configurations.haiku-only.rewriter",
     "Jev reads only answers and facts"),
    (lambda d: d["configurations"]["haiku-only"].update(claims={"agree": ["haiku", "sonnet"]}),
     "configurations.haiku-only.claims", "claims combine with union"),
    (lambda d: d["configurations"]["haiku-only"].update(facts={"union": ["haiku", "sonnet"]}),
     "configurations.haiku-only.facts", "answers and facts combine with agree"),
    (lambda d: d["configurations"]["haiku-only"].update(rewriter={"agree": ["haiku", "sonnet"]}),
     "configurations.haiku-only.rewriter", "a rewriter is one model"),
    (lambda d: d["configurations"]["haiku-only"].update(min_confidence=1.5), "configurations.haiku-only.min_confidence",
     "between 0 and 1"),
    (lambda d: d["configurations"]["haiku-only"].pop("facts"), "configurations.haiku-only", "missing required key"),
    (lambda d: d["models"].update(bad=3), "models.bad", "a pydantic-ai model string"),
])
def test_bad_configs_name_the_path(change, path, message):
    import copy
    data = copy.deepcopy(DATA)
    change(data)
    got = decode_config(data)
    assert isinstance(got, Failure)
    err = got.failure()
    assert err.path == path and message in err.message, err


def test_load_config_reads_yaml(tmp_path):
    (tmp_path / "readers.yaml").write_text("models: {t: test}\nconfigurations:\n"
                                          "  x: {answers: t, facts: t, claims: t, rewriter: t}\n")
    assert load_config(tmp_path / "readers.yaml").unwrap().configurations[0].name == "x"
    assert isinstance(load_config(tmp_path / "nope.yaml"), Failure)


def test_only_the_models_a_configuration_uses_are_built():
    data = {"models": {"t": "test", "broken": "nosuchprovider:x"},
            "configurations": {"x": {"answers": "t", "facts": "t", "claims": "t", "rewriter": "t"}}}
    [cfg] = build(decode_config(data).unwrap()).unwrap()
    assert cfg.name == "x"
