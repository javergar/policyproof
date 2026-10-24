"""`policyproof eval CASES --readers READERS`: run the cases for each reader configuration and gate the result.
`policyproof studio ...` is handed to `policyproof.studio.cli`.

Exit codes: 0 every selected configuration passes its gate; 1 one fails; 2 the cases, the policy or the reader
configuration is invalid, or an extra is missing. Everything is checked before the first model call.
"""
import argparse
import asyncio
import sys
from collections.abc import Mapping, Sequence
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

from returns.result import Failure, Success

from policyproof.core._result import unreachable
from policyproof.eval.cases import load
from policyproof.eval.report import gate, render_text, to_json
from policyproof.eval.run import evaluate

if TYPE_CHECKING:
    from pydantic_ai.models import Model


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="policyproof", description="Prove what an agent may decide and say.")
    sub = p.add_subparsers(dest="command", required=True)
    e = sub.add_parser("eval", help="evaluate reader configurations on a case file and gate the result")
    e.add_argument("cases", type=Path, help="the case file (YAML)")
    e.add_argument("--readers", type=Path, required=True, help="the reader configurations (YAML)")
    e.add_argument("--only", action="append", metavar="NAME", help="run only this configuration (repeatable)")
    e.add_argument("--runs", type=int, default=3, help="runs per case (default 3)")
    e.add_argument("--concurrency", type=int, default=4, help="model calls at once (default 4)")
    e.add_argument("--max-conservative", type=float, default=0.1,
                   help="the largest share of conservative cases the gate allows (default 0.1)")
    e.add_argument("--json", type=Path, metavar="OUT", help="also write the report as JSON")
    st = sub.add_parser("studio", help="open the studio on a markdown policy (policyproof studio --help)",
                        add_help=False)
    st.add_argument("rest", nargs=argparse.REMAINDER)
    return p


def _fail(message: str) -> int:
    print(message, file=sys.stderr)
    return 2


def main(argv: Sequence[str] | None = None, *, models: "Mapping[str, Model] | None" = None) -> int:
    """`models` replaces the configuration's model strings (tests pass scripted models)."""
    args = _parser().parse_args(argv)
    if args.command == "studio":
        try:
            from policyproof.studio.cli import main as studio
        except ImportError as e:
            return _fail(f"the studio needs an extra: pip install 'policyproof[studio]' ({e})")
        return studio(args.rest)
    if args.runs < 1:
        return _fail("--runs must be at least 1")
    if args.concurrency < 1:
        return _fail("--concurrency must be at least 1")
    if not 0 <= args.max_conservative <= 1:
        return _fail("--max-conservative must be between 0 and 1")
    if args.json and not args.json.parent.is_dir():
        return _fail(f"can't write the report: {args.json.parent} does not exist")
    if args.json:
        try:  # open it now, so a path that can't be written fails before the paid run, not after it
            with args.json.open("a"):
                pass
        except OSError as e:
            return _fail(f"can't write the report: {args.json}: {e.strerror}")
    match load(args.cases):
        case Failure(err):
            return _fail(f"{args.cases}: {err}")
        case Success(cases) if not cases.cases:
            return _fail(f"{args.cases} has no cases")
        case Success(cases):
            pass
        case _:
            unreachable()
    try:
        from policyproof.eval.config import build, load_config
    except ImportError as e:
        return _fail(f"reading text needs an extra: pip install 'policyproof[llm]' ({e})")
    match load_config(args.readers):
        case Failure(err):
            return _fail(f"{args.readers}: {err}")
        case Success(cf):
            pass
        case _:
            unreachable()
    if args.only:
        names = {s.name for s in cf.configurations}
        unknown = [n for n in args.only if n not in names]
        if unknown:
            return _fail(f"no configuration named {unknown[0]!r} (configurations: {', '.join(sorted(names))})")
        cf = replace(cf, configurations=tuple(s for s in cf.configurations if s.name in args.only))
    match build(cf, models):
        case Failure(err):
            return _fail(f"{args.readers}: {err}")
        case Success(configurations):
            pass
        case _:
            unreachable()
    report = asyncio.run(evaluate(cases, configurations, runs=args.runs, concurrency=args.concurrency))
    print(render_text(report, args.max_conservative), end="")
    if args.json:
        args.json.write_text(to_json(report))
    return 0 if all(gate(r, args.max_conservative).passed for r in report.configurations) else 1


def entry() -> None:
    raise SystemExit(main())
