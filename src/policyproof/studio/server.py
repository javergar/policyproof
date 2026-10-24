"""The studio's local HTTP server: the built page and a JSON API over the session. It binds to 127.0.0.1 only (see
`studio.cli`) and every API request and the page itself need the per-run token, because it reads and writes files.
The page gets the token in a `<meta name="studio-token">`; the bundle's own files need none."""
from __future__ import annotations

import secrets
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path

from returns.result import Failure, Success
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, PlainTextResponse, Response
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from policyproof.core._result import unreachable
from policyproof.studio import wire as w
from policyproof.studio.schema import dump, parse
from policyproof.studio.session import Session, Studio

STATIC = Path(__file__).with_name("static")


def _json(reply: w.Reply, status: int = 200) -> Response:
    return Response(dump(reply), status_code=status, media_type="application/json")


def app(studio: Studio, token: str, static: Path = STATIC, *, open_doc: Path | None = None) -> Starlette:
    def allowed(request: Request) -> bool:
        given = request.query_params.get("t") or request.headers.get("x-studio-token") or ""
        return secrets.compare_digest(given, token)

    forbidden = PlainTextResponse("This page needs the link the studio printed when it started.", status_code=403)

    async def page(request: Request) -> Response:
        if not allowed(request):
            return forbidden
        html = (static / "index.html").read_text()
        return HTMLResponse(html.replace("<head>", f'<head><meta name="studio-token" content="{token}">', 1))

    async def state(request: Request) -> Response:
        if not allowed(request):
            return forbidden
        async with studio.lock:
            return _json(studio.state())

    async def outside(request: Request) -> Response:
        if not allowed(request):
            return forbidden
        async with studio.lock:
            return _json(studio.session.outside() if studio.session else w.OutsideReply(False))

    async def locked(run: Callable[[Session], Awaitable[w.Reply]]) -> Response:
        async with studio.lock:
            if studio.session is None:
                return _json(w.ErrorReply("Open a document first."))
            return _json(await run(studio.session))

    def act[T](kind: type[T], run: Callable[[Session, T], Awaitable[w.Reply]]) -> Callable[[Request],
                                                                                     Awaitable[Response]]:
        async def handler(request: Request) -> Response:
            if not allowed(request):
                return forbidden
            match parse(kind, await request.body()):
                case Success(body):
                    return await locked(lambda s: run(s, body))
                case Failure(message):
                    return _json(w.ErrorReply(f"The request wasn't understood: {message}"), 400)
                case _:
                    unreachable()
        return handler

    def bare(run: Callable[[Session], Awaitable[w.Reply]]) -> Callable[[Request], Awaitable[Response]]:
        async def handler(request: Request) -> Response:
            return await locked(run) if allowed(request) else forbidden
        return handler

    async def start(request: Request) -> Response:
        if not allowed(request):
            return forbidden
        match parse(w.StartRequest, await request.body()):
            case Success(req):
                async with studio.lock:
                    return _json(await studio.start(req))
            case Failure(message):
                return _json(w.ErrorReply(f"The request wasn't understood: {message}"), 400)
            case _:
                unreachable()

    @asynccontextmanager
    async def lifespan(_: Starlette) -> AsyncIterator[None]:
        if open_doc is not None:  # opened here, on the server's own event loop, which the model clients then use
            async with studio.lock:
                await studio.start(w.StartRequest(str(open_doc), None, None))
        yield

    routes = [
        Route("/", page),
        Route("/api/state", state),
        Route("/api/outside", outside),
        Route("/api/start", start, methods=["POST"]),
        Route("/api/answer", act(w.AnswerRequest, Session.answer), methods=["POST"]),
        Route("/api/group", act(w.GroupRequest, Session.answer_group), methods=["POST"]),
        Route("/api/reword", act(w.RewordRequest, Session.reword), methods=["POST"]),
        Route("/api/accept", act(w.AcceptRequest, Session.accept), methods=["POST"]),
        Route("/api/dismiss", act(w.DismissRequest, Session.dismiss), methods=["POST"]),
        Route("/api/resolve", act(w.ResolveRequest, Session.resolve), methods=["POST"]),
        Route("/api/undo", bare(Session.undo), methods=["POST"]),
        Route("/api/extract-again", bare(Session.extract_again), methods=["POST"]),
        Mount("/assets", StaticFiles(directory=static / "assets", check_dir=False)),
    ]
    return Starlette(routes=routes, lifespan=lifespan)
