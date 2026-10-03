"""L3, L4 (the evaluation half) and L6 over generated well-typed expressions."""
from hypothesis import given
from hypothesis import strategies as st
from returns.pipeline import is_successful
from strategies import SIG, VARS, envs, exprs

from policyproof.core.semantics import evaluate, free_vars, simplify, substitute
from policyproof.core.syntax import BOOL, INT, REAL, BoolLit, EnumLit, IntLit, Lit, RealLit
from policyproof.core.typecheck import sort_of

ANY = exprs(BOOL) | exprs(INT) | exprs(REAL)


def _same_sort(v: Lit, expected) -> bool:
    kinds = {BOOL: BoolLit, INT: IntLit, REAL: RealLit}
    return isinstance(v, kinds[expected]) if expected in kinds else isinstance(v, EnumLit)


@given(ANY, envs(), st.sets(st.sampled_from(sorted(VARS))))
def test_l3_substitution_is_sound(e, env, names):
    sigma = {n: env[n] for n in names}
    rho = {n: v for n, v in env.items() if n not in names}
    assert evaluate(substitute(e, sigma), rho) == evaluate(e, sigma | rho)
    assert free_vars(substitute(e, sigma)) == free_vars(e) - names


@given(ANY, envs())
def test_l4_simplify_preserves_meaning(e, env):
    assert evaluate(simplify(e), env) == evaluate(e, env)


@given(ANY)
def test_l4_simplify_is_idempotent(e):
    assert simplify(simplify(e)) == simplify(e)


@given(ANY, envs())
def test_l6_well_typed_expressions_evaluate_to_their_sort(e, env):
    sort = sort_of(SIG, e).unwrap()
    result = evaluate(e, env)
    assert is_successful(result) and _same_sort(result.unwrap(), sort)


@given(ANY)
def test_simplify_preserves_sort(e):
    assert sort_of(SIG, simplify(e)) == sort_of(SIG, e)
