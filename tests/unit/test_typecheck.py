from dataclasses import replace

from returns.result import Failure, Success

from policyproof.core.syntax import (
    BOOL,
    INT,
    REAL,
    And,
    Arith,
    Ask,
    BoolLit,
    Cmp,
    Define,
    Derived,
    EnumLit,
    EnumSort,
    In,
    IntLit,
    Outcome,
    Policy,
    System,
    Var,
    Variable,
    When,
)
from policyproof.core.typecheck import (
    BadArity,
    Duplicate,
    Signature,
    SortMismatch,
    UnknownName,
    UnknownValue,
    check_policy,
    sort_of,
)

FARE = EnumSort("Fare", ("LITE", "FLEX"))
SIG = Signature({"Fare": FARE}, {"b": BOOL, "n": INT, "x": REAL, "fare": FARE})


def test_sorts_of_well_typed_expressions():
    assert sort_of(SIG, Cmp("ge", Var("n"), IntLit(3))) == Success(BOOL)
    assert sort_of(SIG, Arith("add", (Var("n"), IntLit(1)))) == Success(INT)
    assert sort_of(SIG, In(Var("fare"), (EnumLit("Fare", "LITE"),))) == Success(BOOL)
    assert sort_of(SIG, Cmp("eq", Var("fare"), EnumLit("Fare", "FLEX"))) == Success(BOOL)


def test_sort_errors():
    assert sort_of(SIG, Var("nope"), "R1") == Failure(UnknownName("nope", "R1"))
    assert sort_of(SIG, EnumLit("Fare", "GOLD"), "R1") == Failure(UnknownValue("Fare", "GOLD", "R1"))
    assert sort_of(SIG, And((Var("b"), Var("n"))), "R1") == Failure(SortMismatch("Bool", INT, "R1"))
    assert sort_of(SIG, Cmp("lt", Var("b"), BoolLit(True)), "R1") == Failure(SortMismatch("Int or Real", BOOL, "R1"))
    assert sort_of(SIG, Arith("add", (Var("n"), Var("x"))), "R1") == Failure(SortMismatch("Int", REAL, "R1"))
    assert sort_of(SIG, Arith("sub", (Var("n"),)), "R1") == Failure(BadArity("sub", 1, "R1"))


BASE = Policy(
    name="p", version="1", sorts=(FARE,),
    variables=(Variable("fare", FARE, System(), ""), Variable("b", BOOL, Ask("B?"), ""),
               Variable("ok", BOOL, Derived(), "")),
    rules=(When("R1", Cmp("eq", Var("fare"), EnumLit("Fare", "FLEX")), Var("ok")),),
    outcomes=(Outcome("yes", (("ok", BoolLit(True)),)),))


def test_check_policy_accepts_a_well_formed_policy():
    assert check_policy(BASE) == Success(BASE)


def test_check_policy_reports_every_problem():
    p = replace(BASE, rules=(When("R1", Var("fare"), Var("ok")), Define("R1", "missing", BoolLit(True))),
                outcomes=(Outcome("yes", (("ok", IntLit(1)),)),))
    match check_policy(p):
        case Failure(found):
            assert set(found) == {Duplicate("rule", "R1"), SortMismatch("Bool", FARE, "R1"),
                                  UnknownName("missing", "R1"), SortMismatch("Bool", INT, "outcomes.yes")}
        case _:
            raise AssertionError("expected a failure")
