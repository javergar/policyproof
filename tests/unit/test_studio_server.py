"""The studio's local server: a token on every request, JSON replies that meet the schema, 127.0.0.1 only."""
import json

import jsonschema
from starlette.testclient import TestClient
from test_studio_session import TEXT, opened, ports

from policyproof.studio import cli
from policyproof.studio.schema import api_schema
from policyproof.studio.server import app
from policyproof.studio.session import Studio

TOKEN = "secret-token"
HEADERS = {"X-Studio-Token": TOKEN}
REPLY = {"$defs": api_schema()["$defs"], "$ref": "#/$defs/Reply"}


def client(tmp_path, studio=None) -> TestClient:
    static = tmp_path / "static"
    (static / "assets").mkdir(parents=True)
    (static / "index.html").write_text("<html><head><title>Studio</title></head><body></body></html>")
    (static / "assets" / "app.js").write_text("console.log(1)")
    if studio is None:
        session = opened(tmp_path)
        studio = Studio(tmp_path, session.ports, session)
    return TestClient(app(studio, TOKEN, static))


def reply(response):
    data = response.json()
    jsonschema.validate(data, REPLY)
    return data


def test_requests_need_the_token(tmp_path):
    c = client(tmp_path)
    assert c.get("/api/state").status_code == 403
    assert c.get("/api/state", headers={"X-Studio-Token": "wrong"}).status_code == 403
    assert c.post("/api/undo").status_code == 403
    assert reply(c.get("/api/state", headers=HEADERS))["kind"] == "state"
    assert reply(c.get(f"/api/state?t={TOKEN}"))["kind"] == "state"


def test_the_page_carries_the_token(tmp_path):
    c = client(tmp_path)
    assert c.get("/").status_code == 403
    page = c.get(f"/?t={TOKEN}")
    assert page.status_code == 200 and f'<meta name="studio-token" content="{TOKEN}">' in page.text
    assert c.get("/assets/app.js").text == "console.log(1)"


def test_state_then_answer_then_accept_over_http(tmp_path):
    c = client(tmp_path)
    proposed = reply(c.post("/api/answer", headers=HEADERS, json={"key": "clash:C4+C5", "option": 0, "text": ""}))
    assert proposed["kind"] == "proposal"
    accepted = reply(c.post("/api/accept", headers=HEADERS, json={"proposal": proposed["proposal"]["id"],
                                                                   "switch": []}))
    assert accepted["kind"] == "state" and accepted["state"]["version"] == 1
    assert reply(c.get("/api/outside", headers=HEADERS)) == {"kind": "outside", "changed": False}
    undone = reply(c.post("/api/undo", headers=HEADERS))
    assert undone["kind"] == "state" and (tmp_path / "couriers.md").read_text() == TEXT


def test_a_bad_body_is_a_400_error_reply(tmp_path):
    c = client(tmp_path)
    r = c.post("/api/answer", headers=HEADERS, content=b'{"key": 3}')
    assert r.status_code == 400 and reply(r)["kind"] == "error"
    r = c.post("/api/answer", headers=HEADERS, content=b"not json")
    assert r.status_code == 400 and reply(r)["kind"] == "error"


def test_without_a_document_the_page_asks_for_one(tmp_path):
    c = client(tmp_path, Studio(tmp_path, ports(extracted=(__import__("studio_fixtures").EXTRACTION,))))
    assert reply(c.get("/api/state", headers=HEADERS))["kind"] == "start"
    assert reply(c.post("/api/undo", headers=HEADERS))["kind"] == "error"
    started = reply(c.post("/api/start", headers=HEADERS, json={"path": None, "name": "couriers", "text": TEXT}))
    assert started["kind"] == "state"


def test_the_cli_binds_to_localhost_only(tmp_path):
    doc = tmp_path / "couriers.md"
    opened(tmp_path)
    plan = cli.plan([str(doc), "--port", "8765", "--no-browser"]).unwrap()
    assert plan.config.host == "127.0.0.1" and plan.config.port == 8765
    assert plan.url.startswith("http://127.0.0.1:8765/?t=") and len(plan.token) >= 16


def test_the_cli_refuses_a_document_with_no_policy_and_no_model(tmp_path):
    doc = tmp_path / "new.md"
    doc.write_text(TEXT)
    got = cli.plan([str(doc), "--no-browser"])
    assert "--model" in got.failure()
    assert "doesn't exist" in cli.plan([str(tmp_path / "missing.md")]).failure()


def test_the_schema_is_served_shape_for_shape(tmp_path):
    data = client(tmp_path).get("/api/state", headers=HEADERS).json()
    assert json.loads(json.dumps(data)) == data


def test_policyproof_studio_is_a_subcommand(tmp_path, capsys):
    from policyproof.eval.cli import main
    assert main(["studio", str(tmp_path / "missing.md")]) == 2
    assert "doesn't exist" in capsys.readouterr().err


def test_the_built_page_is_served(tmp_path):
    from policyproof.studio.server import STATIC
    session = opened(tmp_path)
    c = TestClient(app(Studio(tmp_path, session.ports, session), TOKEN))
    page = c.get(f"/?t={TOKEN}")
    assert page.status_code == 200 and '<div id="root"></div>' in page.text
    script = next(p for p in (STATIC / "assets").iterdir() if p.suffix == ".js")
    assert c.get(f"/assets/{script.name}").status_code == 200
