"""The API's JSON Schema, generated from `studio.wire` with pydantic, and the server's encoding and parsing with it.
`python -m policyproof.studio.schema` rewrites `api.schema.json`, which the page's types are generated from."""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter, ValidationError
from returns.result import Failure, Result, Success

from policyproof.studio.wire import (
    AcceptRequest,
    AnswerRequest,
    DismissRequest,
    GroupRequest,
    Reply,
    ResolveRequest,
    RewordRequest,
    StartRequest,
)

SCHEMA = Path(__file__).with_name("api.schema.json")


@dataclass(frozen=True, slots=True)
class Api:
    """Not sent: the root the schema hangs every reply and request from."""

    reply: Reply
    answer: AnswerRequest
    group: GroupRequest
    reword: RewordRequest
    accept: AcceptRequest
    dismiss: DismissRequest
    resolve: ResolveRequest
    start: StartRequest


def _require_all(node: Any) -> None:
    """Every field is always sent, defaults included (`kind`), so every property is required."""
    if isinstance(node, dict):
        if node.get("type") == "object" and "properties" in node:
            node["required"] = list(node["properties"])
        for v in node.values():
            _require_all(v)
    elif isinstance(node, list):
        for v in node:
            _require_all(v)


def api_schema() -> dict[str, Any]:
    schema = TypeAdapter(Api).json_schema(mode="serialization")
    _require_all(schema)
    return schema


def schema_text() -> str:
    return json.dumps(api_schema(), indent=2, sort_keys=True) + "\n"


_REPLY: TypeAdapter[Reply] = TypeAdapter(Reply)


def dump(reply: Reply) -> bytes:
    return _REPLY.dump_json(reply)


def parse[T](kind: type[T], body: bytes) -> Result[T, str]:
    try:
        return Success(TypeAdapter(kind).validate_json(body))
    except ValidationError as e:
        return Failure("; ".join(f"{'.'.join(str(x) for x in err['loc']) or 'body'}: {err['msg']}"
                                 for err in e.errors()))


if __name__ == "__main__":
    SCHEMA.write_text(schema_text())
    sys.exit(0)
