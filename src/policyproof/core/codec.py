"""The YAML policy format: decoding (with paths and line/column positions) and encoding.

Input is first turned into a small `Tree` (scalars, sequences, maps, each with an optional position), so YAML text and
in-memory data decode through the same code. Strings in, strings out: reading files belongs to `policyproof.effects`.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from fractions import Fraction
from typing import assert_never, cast

import yaml
from returns.result import Failure, Result, Success

from policyproof.core._result import sequence
from policyproof.core.syntax import (
    ARITH_OPS,
    BOOL,
    CMP_OPS,
    INT,
    REAL,
    And,
    Arith,
    Ask,
    BoolLit,
    BoolSort,
    CheckedPolicy,
    Cmp,
    Constraint,
    Define,
    Derived,
    EnumLit,
    EnumSort,
    Expr,
    Iff,
    Implies,
    In,
    IntLit,
    IntSort,
    Lit,
    Not,
    Or,
    Outcome,
    Policy,
    RealLit,
    RealSort,
    Role,
    Rule,
    Sort,
    System,
    Var,
    Variable,
    When,
)
from policyproof.core.typecheck import Signature, SortError, check_policy, signature

# ---- trees


@dataclass(frozen=True, slots=True)
class Pos:
    line: int  # 1-based
    column: int  # 1-based


type Atom = str | int | float | bool | None


@dataclass(frozen=True, slots=True)
class Scalar:
    value: Atom
    pos: Pos | None = None
    raw: str | None = None  # the text as written in YAML, when decoded from YAML


@dataclass(frozen=True, slots=True)
class Seq:
    items: tuple[Tree, ...]
    pos: Pos | None = None


@dataclass(frozen=True, slots=True)
class Map:
    items: tuple[tuple[str, Tree], ...]
    pos: Pos | None = None


type Tree = Scalar | Seq | Map
type Data = str | int | bool | list[Data] | dict[str, Data] | None


@dataclass(frozen=True, slots=True)
class DecodeError:
    path: str
    message: str
    pos: Pos | None = None

    def __str__(self) -> str:
        at = f" (line {self.pos.line}, column {self.pos.column})" if self.pos else ""
        return f"{self.path or '<root>'}{at}: {self.message}"


@dataclass(frozen=True, slots=True)
class IllTyped:
    errors: tuple[SortError, ...]


type PolicyError = DecodeError | IllTyped


def from_data(obj: object) -> Result[Tree, DecodeError]:
    """Plain Python data (as from `json.loads` or `yaml.safe_load`) as a tree, without positions."""
    match obj:
        case str() | int() | float() | bool() | None:
            return Success(Scalar(obj))
        case list() | tuple():
            return sequence(from_data(x) for x in cast(list[object], obj)).map(Seq)
        case dict():
            items = cast(dict[object, object], obj).items()
            bad = [k for k, _ in items if not isinstance(k, str)]
            if bad:
                return Failure(DecodeError("", f"map keys must be strings, got {bad[0]!r}"))
            return sequence(from_data(v).map(lambda t, k=k: (str(k), t)) for k, v in items).map(Map)
        case _:
            return Failure(DecodeError("", f"unsupported value {obj!r}"))


def from_yaml_text(text: str) -> Result[Tree, DecodeError]:
    """YAML text as a tree that keeps each node's line and column."""
    try:
        node = yaml.compose(text, Loader=yaml.SafeLoader)
    except yaml.YAMLError as err:
        mark = getattr(err, "problem_mark", None)
        pos = Pos(mark.line + 1, mark.column + 1) if mark is not None else None
        problem = str(getattr(err, "problem", err))
        hint = (" (inside { } or [ ], quote text that contains commas, colons or question marks)"
                if "expected ','" in problem else "")
        return Failure(DecodeError("", f"invalid YAML: {problem}{hint}", pos))
    if node is None:
        return Failure(DecodeError("", "the document is empty"))
    tree = _from_node(node)
    duplicate = _duplicate_key(tree, "")
    return Failure(duplicate) if duplicate else Success(tree)


def _duplicate_key(t: Tree, path: str) -> DecodeError | None:
    """YAML allows repeated keys and keeps one silently; a policy must not."""
    match t:
        case Map(items, pos):
            seen: set[str] = set()
            for key, _ in items:
                if key in seen:
                    return DecodeError(path, f"duplicate key {key!r}", pos)
                seen.add(key)
            return next((d for k, v in items if (d := _duplicate_key(v, _join(path, k)))), None)
        case Seq(items):
            return next((d for i, x in enumerate(items) if (d := _duplicate_key(x, _join(path, i)))), None)
        case Scalar():
            return None
        case _:
            raise AssertionError("unreachable")


def _from_node(node: yaml.Node) -> Tree:
    pos = Pos(node.start_mark.line + 1, node.start_mark.column + 1)
    if isinstance(node, yaml.MappingNode):
        return Map(tuple((str(k.value), _from_node(v)) for k, v in node.value), pos)
    if isinstance(node, yaml.SequenceNode):
        return Seq(tuple(_from_node(x) for x in node.value), pos)
    value = yaml.SafeLoader("").construct_object(node, deep=True)
    atom = value if isinstance(value, str | int | float | bool) or value is None else str(value)
    return Scalar(atom, pos, str(node.value))


def _err(path: str, t: Tree, message: str) -> Failure[DecodeError]:
    return Failure(DecodeError(path, message, t.pos))


def _join(path: str, key: str | int) -> str:
    return f"{path}[{key}]" if isinstance(key, int) else (f"{path}.{key}" if path else key)


# ---- expressions

UNARY = {"not"}
NARY_BOOL = {"and": And, "or": Or}
BINARY_BOOL = {"implies": Implies, "iff": Iff}


def decode_expr(sig: Signature, t: Tree, path: str = "") -> Result[Expr, DecodeError]:
    match t:
        case Scalar(bool(), _, raw) if raw is not None and raw.lower() not in ("true", "false"):
            return _err(path, t, f"YAML reads {raw} as true/false: write true or false for a Boolean, or quote it "
                                 f'("{raw}") for an enum value')
        case Scalar(bool() as b):
            return Success(BoolLit(b))
        case Scalar(int() as n):
            return Success(IntLit(n))
        case Scalar(float()):
            return _err(path, t, 'write decimals as {real: "2.5"}, never as a YAML float')
        case Scalar(str() as name):
            return _name(sig, name, path, t)
        case Scalar(None):
            return _err(path, t, "an expression is missing here")
        case Seq():
            return _err(path, t, "a list is not an expression; use {and: [...]} or {or: [...]}")
        case Map(items) if len(items) != 1:
            return _err(path, t, f"an operator node has exactly one key, found {len(items)}")
        case Map(((op, arg),)):
            return _operator(sig, op, arg, _join(path, op))
        case _:
            raise AssertionError("unreachable")


def _name(sig: Signature, name: str, path: str, t: Tree) -> Result[Expr, DecodeError]:
    if name in sig.variables:
        return Success(Var(name))
    if "." in name:
        sort, _, value = name.partition(".")
        if sort in sig.sorts and value in sig.sorts[sort].values:
            return Success(EnumLit(sort, value))
        return _err(path, t, f"unknown value {name!r}")
    owners = [s.name for s in sig.sorts.values() if name in s.values]
    if len(owners) == 1:
        return Success(EnumLit(owners[0], name))
    if owners:
        return _err(path, t, f"{name!r} is a value of {', '.join(owners)}; qualify it, e.g. {owners[0]}.{name}")
    return _err(path, t, f"unknown name {name!r} (not a variable or an enum value)")


def _operands(arg: Tree, path: str, want: str) -> Result[tuple[Tree, ...], DecodeError]:
    if not isinstance(arg, Seq):
        return _err(path, arg, f"expected a list of {want}")
    n = len(arg.items)
    ok = {"two": n == 2, "two or more": n >= 2, "one or more": n >= 1}[want]
    return Success(arg.items) if ok else _err(path, arg, f"expected {want} operands, found {n}")


def _each(sig: Signature, items: tuple[Tree, ...], path: str) -> Result[tuple[Expr, ...], DecodeError]:
    return sequence(decode_expr(sig, x, _join(path, i)) for i, x in enumerate(items))


def _operator(sig: Signature, op: str, arg: Tree, path: str) -> Result[Expr, DecodeError]:
    if op == "not":
        return decode_expr(sig, arg, path).map(Not)
    if op in NARY_BOOL:
        build = NARY_BOOL[op]
        return _operands(arg, path, "two or more").bind(lambda xs: _each(sig, xs, path)).map(build)
    if op in BINARY_BOOL:
        pair = BINARY_BOOL[op]
        return _operands(arg, path, "two").bind(lambda xs: _each(sig, xs, path)).map(lambda es: pair(es[0], es[1]))
    for cmp in CMP_OPS:
        if op == cmp:
            return _operands(arg, path, "two").bind(lambda xs: _each(sig, xs, path)).map(
                lambda es, c=cmp: Cmp(c, es[0], es[1]))
    for ar in ARITH_OPS:
        if op == ar:
            want = "two" if ar == "sub" else "two or more"
            return _operands(arg, path, want).bind(lambda xs: _each(sig, xs, path)).map(
                lambda es, a=ar: Arith(a, es))
    if op == "in":
        return _operands(arg, path, "two").bind(lambda xs: _membership(sig, xs, path))
    if op == "real":
        return _real(arg, path)
    return _err(path, arg, f"unknown operator {op!r}")


def _membership(sig: Signature, xs: tuple[Tree, ...], path: str) -> Result[Expr, DecodeError]:
    subject, values = xs
    if not isinstance(values, Seq) or not values.items:
        return _err(_join(path, 1), values, "expected a non-empty list of values")
    return decode_expr(sig, subject, _join(path, 0)).bind(
        lambda e: _each(sig, values.items, _join(path, 1)).bind(lambda vs: _literals(vs, values, path)).map(
            lambda lits: In(e, lits)))


def _literals(vs: tuple[Expr, ...], t: Tree, path: str) -> Result[tuple[Lit, ...], DecodeError]:
    lits = tuple(v for v in vs if isinstance(v, BoolLit | IntLit | RealLit | EnumLit))
    return Success(lits) if len(lits) == len(vs) else _err(path, t, "`in` takes literal values only")


def _real(arg: Tree, path: str) -> Result[Expr, DecodeError]:
    if isinstance(arg, Scalar) and isinstance(arg.value, str | int) and not isinstance(arg.value, bool):
        try:
            return Success(RealLit(Fraction(arg.value)))
        except (ValueError, ZeroDivisionError):
            pass
    return _err(path, arg, 'expected a decimal written as a string, e.g. {real: "2.5"} or {real: "5/2"}')


def encode_expr(e: Expr) -> Data:
    match e:
        case BoolLit(v) | IntLit(v):
            return v
        case RealLit(v):
            return {"real": str(v)}
        case EnumLit(sort, value):
            return f"{sort}.{value}"
        case Var(name):
            return name
        case Not(arg):
            return {"not": encode_expr(arg)}
        case And(args):
            return {"and": [encode_expr(a) for a in args]}
        case Or(args):
            return {"or": [encode_expr(a) for a in args]}
        case Implies(lhs, rhs):
            return {"implies": [encode_expr(lhs), encode_expr(rhs)]}
        case Iff(lhs, rhs):
            return {"iff": [encode_expr(lhs), encode_expr(rhs)]}
        case Cmp(op, lhs, rhs):
            return {op: [encode_expr(lhs), encode_expr(rhs)]}
        case Arith(op, args):
            return {op: [encode_expr(a) for a in args]}
        case In(arg, values):
            return {"in": [encode_expr(arg), [encode_expr(v) for v in values]]}
        case _:
            assert_never(e)


# ---- policies


def _field(t: Map, key: str) -> Tree | None:
    return next((v for k, v in t.items if k == key), None)


def _require[T](t: Map, key: str, path: str, read: Callable[[Tree, str], Result[T, DecodeError]]
                ) -> Result[T, DecodeError]:
    v = _field(t, key)
    return read(v, _join(path, key)) if v is not None else _err(path, t, f"missing required key {key!r}")


def _optional[T](t: Map, key: str, path: str, read: Callable[[Tree, str], Result[T, DecodeError]], default: T
                 ) -> Result[T, DecodeError]:
    v = _field(t, key)
    return read(v, _join(path, key)) if v is not None else Success(default)


def _known_keys(t: Map, path: str, allowed: set[str]) -> Result[Map, DecodeError]:
    extra = [(k, v) for k, v in t.items if k not in allowed]
    if not extra:
        return Success(t)
    key, value = extra[0]
    hint = (" (a comma inside { } starts a new key: quote text that contains commas)"
            if isinstance(value, Scalar) and value.value is None else "")
    return _err(_join(path, key), t, f"unknown key {key!r}{hint}")


def _text(t: Tree, path: str) -> Result[str, DecodeError]:
    if isinstance(t, Scalar) and isinstance(t.value, str):
        return Success(t.value)
    if isinstance(t, Scalar) and isinstance(t.value, bool):
        return _err(path, t, 'YAML reads YES, NO, ON, OFF, TRUE and FALSE as true/false; quote it, e.g. "YES"')
    return _err(path, t, "expected text (quote numbers such as \"1.0\")")


def _flag(t: Tree, path: str) -> Result[bool, DecodeError]:
    if isinstance(t, Scalar) and isinstance(t.value, bool):
        return Success(t.value)
    return _err(path, t, "expected true or false")


def _map(t: Tree, path: str) -> Result[Map, DecodeError]:
    return Success(t) if isinstance(t, Map) else _err(path, t, "expected a map")


def _seq(t: Tree, path: str) -> Result[Seq, DecodeError]:
    return Success(t) if isinstance(t, Seq) else _err(path, t, "expected a list")


def _sorts(t: Tree, path: str) -> Result[tuple[EnumSort, ...], DecodeError]:
    return _map(t, path).bind(lambda m: sequence(
        _seq(v, _join(path, k)).bind(lambda s, k=k: sequence(
            _text(x, _join(_join(path, k), i)) for i, x in enumerate(s.items)).map(lambda vs, k=k: EnumSort(k, vs)))
        for k, v in m.items))


def _sort(sorts: dict[str, EnumSort], t: Tree, path: str) -> Result[Sort, DecodeError]:
    builtin: dict[str, Sort] = {"Bool": BOOL, "Int": INT, "Real": REAL}
    return _text(t, path).bind(lambda n: Success(builtin[n]) if n in builtin else (
        Success(sorts[n]) if n in sorts else _err(path, t, f"unknown sort {n!r}")))


def _role(m: Map, path: str) -> Result[Role, DecodeError]:
    def build(name: str) -> Result[Role, DecodeError]:
        match name:
            case "system":
                return Success(System())
            case "derived":
                return Success(Derived())
            case "ask":
                return _require(m, "question", path, _text).bind(
                    lambda q: _optional(m, "confirm_volunteered", path, _flag, True).map(lambda c: Ask(q, c)))
            case _:
                return _err(_join(path, "role"), m, f"role must be system, ask or derived, not {name!r}")
    return _require(m, "role", path, _text).bind(build)


def _variable(sorts: dict[str, EnumSort], name: str, t: Tree, path: str) -> Result[Variable, DecodeError]:
    keys = {"sort", "role", "description", "question", "confirm_volunteered"}
    return _map(t, path).bind(lambda m: _known_keys(m, path, keys)).bind(lambda m: _require(
        m, "sort", path, lambda x, p: _sort(sorts, x, p)).bind(lambda s: _role(m, path).bind(
            lambda r: _optional(m, "description", path, _text, "").map(lambda d: Variable(name, s, r, d)))))


def _variables(sorts: dict[str, EnumSort], t: Tree, path: str) -> Result[tuple[Variable, ...], DecodeError]:
    return _map(t, path).bind(lambda m: sequence(_variable(sorts, k, v, _join(path, k)) for k, v in m.items))


def _rule(sig: Signature, t: Tree, path: str) -> Result[Rule, DecodeError]:
    keys = {"id", "source", "explain", "when", "then", "define", "constraint"}

    def expr(m: Map, key: str) -> Result[Expr, DecodeError]:
        return _require(m, key, path, lambda x, p: decode_expr(sig, x, p))

    def build(m: Map, rid: str, source: str | None, explain: str | None) -> Result[Rule, DecodeError]:
        shapes = [k for k in ("when", "define", "constraint") if _field(m, k) is not None]
        if len(shapes) != 1:
            return _err(path, m, "a rule has exactly one of: when/then, define, constraint")
        match shapes[0]:
            case "when":
                return expr(m, "when").bind(lambda w: expr(m, "then").map(
                    lambda th: When(rid, w, th, source, explain)))
            case "define":
                dpath = _join(path, "define")
                return _require(m, "define", path, _map).bind(lambda d: _known_keys(d, dpath, {"var", "as"})).bind(
                    lambda d: _require(d, "var", dpath, _text).bind(
                        lambda v: _require(d, "as", dpath, lambda x, p: decode_expr(sig, x, p)).map(
                            lambda a: Define(rid, v, a, source, explain))))
            case _:
                return expr(m, "constraint").map(lambda c: Constraint(rid, c, source, explain))

    def opt_text(m: Map, key: str) -> Result[str | None, DecodeError]:
        return _optional(m, key, path, lambda x, p: _text(x, p).map(lambda s: cast(str | None, s)), None)

    return _map(t, path).bind(lambda m: _known_keys(m, path, keys)).bind(lambda m: _require(m, "id", path, _text).bind(
        lambda rid: opt_text(m, "source").bind(lambda src: opt_text(m, "explain").bind(
            lambda ex: build(m, rid, src, ex)))))


def _outcome(sig: Signature, name: str, t: Tree, path: str) -> Result[Outcome, DecodeError]:
    def literal(var: str, x: Tree) -> Result[tuple[str, Lit], DecodeError]:
        p = _join(path, var)
        return decode_expr(sig, x, p).bind(lambda e: Success((var, e)) if isinstance(
            e, BoolLit | IntLit | RealLit | EnumLit) else _err(p, x, "an outcome assigns literal values only"))
    return _map(t, path).bind(lambda m: sequence(literal(k, v) for k, v in m.items)).map(lambda a: Outcome(name, a))


def decode_tree(t: Tree) -> Result[Policy, DecodeError]:
    """The structural decoding of a policy, before sort checking."""
    keys = {"policy", "version", "sorts", "variables", "rules", "outcomes"}

    def body(m: Map, name: str, version: str, sorts: tuple[EnumSort, ...]) -> Result[Policy, DecodeError]:
        def with_variables(vs: tuple[Variable, ...]) -> Result[Policy, DecodeError]:
            sig = signature(Policy(name, version, sorts, vs, (), ()))
            rules = _require(m, "rules", "", lambda x, p: _seq(x, p).bind(
                lambda s: sequence(_rule(sig, r, _join(p, i)) for i, r in enumerate(s.items))))
            return rules.bind(lambda rs: _optional(m, "outcomes", "", lambda x, p: _map(x, p).bind(
                lambda om: sequence(_outcome(sig, k, v, _join(p, k)) for k, v in om.items)), ()).map(
                lambda os: Policy(name, version, sorts, vs, rs, os)))

        by_name = {s.name: s for s in sorts}
        return _require(m, "variables", "", lambda x, p: _variables(by_name, x, p)).bind(with_variables)

    return _map(t, "").bind(lambda m: _known_keys(m, "", keys)).bind(lambda m: _require(m, "policy", "", _text).bind(
        lambda name: _require(m, "version", "", _text).bind(lambda version: _optional(
            m, "sorts", "", _sorts, ()).bind(lambda sorts: body(m, name, version, sorts)))))


def _checked(r: Result[Policy, DecodeError]) -> Result[CheckedPolicy, PolicyError]:
    return r.alt(lambda e: cast(PolicyError, e)).bind(
        lambda p: check_policy(p).alt(lambda errs: cast(PolicyError, IllTyped(errs))))


def decode(data: object) -> Result[CheckedPolicy, PolicyError]:
    """A checked policy from plain data (e.g. `json.loads` output)."""
    return _checked(from_data(data).bind(decode_tree))


def from_yaml(text: str) -> Result[CheckedPolicy, PolicyError]:
    """A checked policy from YAML text; decode errors carry line and column."""
    return _checked(from_yaml_text(text).bind(decode_tree))


def _encode_sort(s: Sort) -> str:
    match s:
        case BoolSort():
            return "Bool"
        case IntSort():
            return "Int"
        case RealSort():
            return "Real"
        case EnumSort(name, _):
            return name
        case _:
            assert_never(s)


def _encode_variable(v: Variable) -> dict[str, Data]:
    out: dict[str, Data] = {"sort": _encode_sort(v.sort)}
    match v.role:
        case System():
            out["role"] = "system"
        case Derived():
            out["role"] = "derived"
        case Ask(question, confirm):
            out |= {"role": "ask", "question": question, "confirm_volunteered": confirm}
        case _:
            assert_never(v.role)
    out["description"] = v.description
    return out


def _encode_rule(r: Rule) -> dict[str, Data]:
    out: dict[str, Data] = {"id": r.id}
    if r.source is not None:
        out["source"] = r.source
    match r:
        case When(_, when, then):
            out |= {"when": encode_expr(when), "then": encode_expr(then)}
        case Define(_, var, as_):
            out["define"] = {"var": var, "as": encode_expr(as_)}
        case Constraint(_, expr):
            out["constraint"] = encode_expr(expr)
        case _:
            assert_never(r)
    if r.explain is not None:
        out["explain"] = r.explain
    return out


def encode(p: Policy) -> dict[str, Data]:
    return {
        "policy": p.name,
        "version": p.version,
        "sorts": {s.name: list(s.values) for s in p.sorts},
        "variables": {v.name: _encode_variable(v) for v in p.variables},
        "rules": [_encode_rule(r) for r in p.rules],
        "outcomes": {o.name: {var: encode_expr(lit) for var, lit in o.assignment} for o in p.outcomes},
    }


def to_yaml(p: Policy) -> str:
    return yaml.safe_dump(encode(p), sort_keys=False, allow_unicode=True, width=120)
