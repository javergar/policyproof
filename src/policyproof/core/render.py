"""Display forms of expressions: a readable one-line form, and SMT-LIB. Nothing parses these back."""
from __future__ import annotations

from typing import assert_never

from policyproof.core.syntax import (
    And,
    Arith,
    BoolLit,
    BoolSort,
    Cmp,
    EnumLit,
    EnumSort,
    Expr,
    Iff,
    Implies,
    In,
    IntLit,
    IntSort,
    Not,
    Or,
    RealLit,
    RealSort,
    Var,
)
from policyproof.core.typecheck import Signature

CMP_SYMBOL = {"eq": "=", "ne": "≠", "lt": "<", "le": "≤", "gt": ">", "ge": "≥"}
ARITH_SYMBOL = {"add": "+", "sub": "−", "mul": "×"}
ATOM = 9


def _prec(e: Expr) -> int:
    match e:
        case Iff():
            return 1
        case Implies():
            return 2
        case Or():
            return 3
        case And():
            return 4
        case Not():
            return 5
        case Cmp() | In():
            return 6
        case Arith(op, _):
            return 8 if op == "mul" else 7
        case BoolLit() | IntLit() | RealLit() | EnumLit() | Var():
            return ATOM
        case _:
            assert_never(e)


def _wrap(e: Expr, parent: int) -> str:
    text = pretty(e)
    return f"({text})" if _prec(e) <= parent and _prec(e) != ATOM else text


def pretty(e: Expr) -> str:
    """`delayHours ≥ 3 ∧ ¬hasFlown`: for explanations and traces."""
    match e:
        case BoolLit(v):
            return "true" if v else "false"
        case IntLit(v):
            return str(v)
        case RealLit(v):
            return str(v)
        case EnumLit(_, value):
            return value
        case Var(name):
            return name
        case Not(arg):
            return f"¬{_wrap(arg, ATOM - 1)}"
        case And(args):
            return " ∧ ".join(_wrap(a, 4) for a in args)
        case Or(args):
            return " ∨ ".join(_wrap(a, 3) for a in args)
        case Implies(lhs, rhs):
            return f"{_wrap(lhs, 2)} ⇒ {_wrap(rhs, 2)}"
        case Iff(lhs, rhs):
            return f"{_wrap(lhs, 1)} ⇔ {_wrap(rhs, 1)}"
        case Cmp(op, lhs, rhs):
            return f"{_wrap(lhs, 6)} {CMP_SYMBOL[op]} {_wrap(rhs, 6)}"
        case Arith(op, args):
            return f" {ARITH_SYMBOL[op]} ".join(_wrap(a, _prec(e)) for a in args)
        case In(arg, values):
            return f"{_wrap(arg, 6)} ∈ {{{', '.join(pretty(v) for v in values)}}}"
        case _:
            assert_never(e)


def smt_name(sort: str, value: str) -> str:
    """The SMT-LIB and Z3 name of an enum value; qualified, because two sorts may share a value name."""
    return f"{sort}.{value}"


def to_smtlib(e: Expr) -> str:
    match e:
        case BoolLit(v):
            return "true" if v else "false"
        case IntLit(v):
            return str(v) if v >= 0 else f"(- {-v})"
        case RealLit(v):
            n, d = abs(v.numerator), v.denominator
            body = f"(/ {n}.0 {d}.0)" if d != 1 else f"{n}.0"
            return body if v >= 0 else f"(- {body})"
        case EnumLit(sort, value):
            return f"|{smt_name(sort, value)}|"
        case Var(name):
            return name
        case Not(arg):
            return f"(not {to_smtlib(arg)})"
        case And(args):
            return f"(and {' '.join(map(to_smtlib, args))})" if args else "true"
        case Or(args):
            return f"(or {' '.join(map(to_smtlib, args))})" if args else "false"
        case Implies(lhs, rhs):
            return f"(=> {to_smtlib(lhs)} {to_smtlib(rhs)})"
        case Iff(lhs, rhs):
            return f"(= {to_smtlib(lhs)} {to_smtlib(rhs)})"
        case Cmp("ne", lhs, rhs):
            return f"(distinct {to_smtlib(lhs)} {to_smtlib(rhs)})"
        case Cmp(op, lhs, rhs):
            symbol = {"eq": "=", "lt": "<", "le": "<=", "gt": ">", "ge": ">="}[op]
            return f"({symbol} {to_smtlib(lhs)} {to_smtlib(rhs)})"
        case Arith(op, args):
            return f"({ {'add': '+', 'sub': '-', 'mul': '*'}[op]} {' '.join(map(to_smtlib, args))})"
        case In(arg, values):
            x = to_smtlib(arg)
            return f"(or {' '.join(f'(= {x} {to_smtlib(v)})' for v in values)})" if len(values) > 1 else (
                f"(= {x} {to_smtlib(values[0])})")
        case _:
            assert_never(e)


def smt_declarations(sig: Signature) -> str:
    """`declare-datatypes` for the enum sorts and `declare-const` for the variables."""
    lines = [f"(declare-datatypes () (({s.name} {' '.join(f'|{smt_name(s.name, v)}|' for v in s.values)})))"
             for s in sig.sorts.values()]
    for name, sort in sig.variables.items():
        match sort:
            case BoolSort():
                smt = "Bool"
            case IntSort():
                smt = "Int"
            case RealSort():
                smt = "Real"
            case EnumSort(sname, _):
                smt = sname
            case _:
                assert_never(sort)
        lines.append(f"(declare-const {name} {smt})")
    return "\n".join(lines)
