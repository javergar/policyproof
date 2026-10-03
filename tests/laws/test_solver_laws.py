"""L5: Z3 agrees with the reference semantics. Also: the SMT-LIB rendering means the same as the compiled term."""
import z3
from hypothesis import given
from strategies import COLOR, DECLS, SIG, envs, exprs

from policyproof.core.render import smt_declarations, to_smtlib
from policyproof.core.semantics import evaluate
from policyproof.core.solver import compile, ground, to_z3
from policyproof.core.syntax import BOOL, INT, REAL, Policy
from policyproof.core.typecheck import check_policy, sort_of

EMPTY = compile(check_policy(Policy("laws", "1", (COLOR,), DECLS, (), ())).unwrap())
ANY = exprs(BOOL) | exprs(INT) | exprs(REAL)


@given(ANY, envs())
def test_l5_compile_is_sound(e, env):
    assert ground(EMPTY, e, sort_of(SIG, e).unwrap(), env) == evaluate(e, env).unwrap()


@given(exprs(BOOL))
def test_smtlib_rendering_means_the_same_as_the_compiled_term(e):
    parsed = z3.parse_smt2_string(f"{smt_declarations(SIG)}\n(assert {to_smtlib(e)})", ctx=EMPTY.ctx)
    s = z3.Solver(ctx=EMPTY.ctx)
    s.add(z3.Not(z3.And(*parsed, EMPTY.ctx) == to_z3(EMPTY, e)))
    assert s.check() == z3.unsat
