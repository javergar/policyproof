from fractions import Fraction

from returns.result import Failure, Success

from policyproof.core.render import pretty, to_smtlib
from policyproof.core.semantics import Mismatch, Unbound, evaluate, free_vars, simplify, substitute
from policyproof.core.syntax import (
    And,
    Arith,
    BoolLit,
    Cmp,
    EnumLit,
    Iff,
    Implies,
    In,
    IntLit,
    Not,
    Or,
    RealLit,
    Var,
)

LATE = And((Cmp("ge", Var("days"), IntLit(2)), Not(Var("flown"))))
ENV = {"days": IntLit(3), "flown": BoolLit(False), "fare": EnumLit("Fare", "LITE")}


def test_evaluate():
    assert evaluate(LATE, ENV) == Success(BoolLit(True))
    assert evaluate(Arith("sub", (Var("days"), IntLit(5))), ENV) == Success(IntLit(-2))
    half, three = RealLit(Fraction(1, 2)), RealLit(Fraction(3))
    assert evaluate(Arith("mul", (half, three)), {}) == Success(RealLit(Fraction(3, 2)))
    assert evaluate(In(Var("fare"), (EnumLit("Fare", "FLEX"), EnumLit("Fare", "LITE"))), ENV) == Success(BoolLit(True))
    assert evaluate(Implies(BoolLit(False), Var("flown")), ENV) == Success(BoolLit(True))


def test_evaluate_errors_are_values():
    assert evaluate(LATE, {"days": IntLit(3)}) == Failure(Unbound("flown"))
    assert evaluate(Not(Var("days")), ENV) == Failure(Mismatch("Bool", IntLit(3)))


def test_substitute_and_free_vars():
    assert free_vars(LATE) == {"days", "flown"}
    partial = substitute(LATE, {"days": IntLit(1)})
    assert free_vars(partial) == {"flown"}
    assert simplify(partial) == BoolLit(False)


def test_simplify_examples():
    p, q = Var("p"), Var("q")
    assert simplify(And((p, BoolLit(True), And((q, p))))) == And((p, q))
    assert simplify(Or((p, BoolLit(True)))) == BoolLit(True)
    assert simplify(Not(Not(p))) == p
    assert simplify(Implies(p, BoolLit(False))) == Not(p)
    assert simplify(Iff(BoolLit(False), q)) == Not(q)
    assert simplify(Cmp("ge", Arith("add", (IntLit(1), IntLit(2))), IntLit(3))) == BoolLit(True)
    assert simplify(Cmp("lt", Var("n"), Var("n"))) == BoolLit(False)


def test_pretty_and_smtlib():
    assert pretty(LATE) == "days ≥ 2 ∧ ¬flown"
    assert pretty(Not(And((Var("a"), Var("b"))))) == "¬(a ∧ b)"
    assert pretty(Implies(Or((Var("a"), Var("b"))), Var("c"))) == "a ∨ b ⇒ c"
    assert pretty(Arith("mul", (Arith("add", (Var("a"), IntLit(1))), Var("b")))) == "(a + 1) × b"
    assert to_smtlib(LATE) == "(and (>= days 2) (not flown))"
    assert to_smtlib(Cmp("ne", Var("fare"), EnumLit("Fare", "LITE"))) == "(distinct fare |Fare.LITE|)"
    assert to_smtlib(RealLit(Fraction(-5, 2))) == "(- (/ 5.0 2.0))"
