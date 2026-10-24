"""`policyproof studio [DOC] [--model MODEL] [--port N] [--no-browser]`: open the studio on a markdown policy.

Without DOC the page asks for a document to open or paste. Without --model the studio opens a document that already
has a policy and offers everything that needs no model; extracting and proposing changes need one (any pydantic-ai
model string, e.g. `bedrock:us.anthropic.claude-sonnet-4-5-20250929-v1:0`). Exit codes: 0 after the server stops;
2 when the arguments or the document are unusable.
"""
from __future__ import annotations

import argparse
import secrets
import socket
import sys
import webbrowser
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import uvicorn
from returns.result import Failure, Result, Success

from policyproof.core._result import unreachable
from policyproof.studio.server import app
from policyproof.studio.session import Ports, Studio
from policyproof.studio.workspace import Paths

HOST = "127.0.0.1"


@dataclass(frozen=True, slots=True)
class Plan:
    config: uvicorn.Config
    url: str
    token: str
    browser: bool


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="policyproof studio", description="Fix a policy extracted from a document.")
    p.add_argument("doc", type=Path, nargs="?", help="the markdown policy document")
    p.add_argument("--model", help="a pydantic-ai model string, for extracting and proposing changes")
    p.add_argument("--port", type=int, default=0, help="the port on 127.0.0.1 (default: a free one)")
    p.add_argument("--no-browser", action="store_true", help="print the link but don't open it")
    return p


def _ports(model: str | None) -> Result[Ports, str]:
    if model is None:
        return Success(Ports())
    try:
        from pydantic_ai.models import infer_model

        from policyproof.authoring.llm.drafter import LLMDrafter
        from policyproof.authoring.llm.extractor import LLMExtractor
        from policyproof.authoring.llm.phraser import LLMPhraser
        m = infer_model(model)
    except ImportError as e:
        return Failure(f"--model needs an extra: pip install 'policyproof[studio]' ({e})")
    except Exception as e:  # the provider rejected the model string or its settings
        return Failure(f"--model {model}: {e}")
    return Success(Ports(LLMExtractor(m), LLMDrafter(m), LLMPhraser(m)))


def _free_port() -> int:
    with socket.socket() as s:
        s.bind((HOST, 0))
        return s.getsockname()[1]


def plan(argv: Sequence[str] | None = None) -> Result[Plan, str]:
    args = _parser().parse_args(argv)
    doc: Path | None = args.doc.resolve() if args.doc else None
    if doc is not None and not doc.is_file():
        return Failure(f"{args.doc} doesn't exist")
    if doc is not None and args.model is None and not Paths.of(doc).policy.exists():
        return Failure(f"{doc.name} has no policy yet; start with --model to extract one")
    match _ports(args.model):
        case Success(ports):
            pass
        case Failure(message):
            return Failure(message)
        case _:
            unreachable()
    token = secrets.token_urlsafe(16)
    port = args.port or _free_port()
    studio = Studio(doc.parent if doc else Path.cwd(), ports)
    config = uvicorn.Config(app(studio, token, open_doc=doc), host=HOST, port=port, log_level="warning")
    return Success(Plan(config, f"http://{HOST}:{port}/?t={token}", token, not args.no_browser))


def main(argv: Sequence[str] | None = None) -> int:
    match plan(argv):
        case Success(p):
            pass
        case Failure(message):
            print(message, file=sys.stderr)
            return 2
        case _:
            unreachable()
    print(f"policyproof studio: {p.url}\nPress Ctrl+C to stop.")
    if p.browser:
        webbrowser.open(p.url)
    uvicorn.Server(p.config).run()
    return 0
