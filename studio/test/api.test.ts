import { readFileSync } from "node:fs";
import { describe, expect, test } from "vitest";
import { call, check } from "../src/api";
import { view } from "./sample";

const ok = (body: unknown) => async () => new Response(JSON.stringify(body), { status: 200 });

describe("responses are checked against the schema", () => {
  test("a valid state reply parses", () => {
    const r = check({ kind: "state", state: view() });
    expect(r.ok && r.value.kind).toBe("state");
  });

  test("a malformed response is an error", () => {
    const { version: _, ...missing } = view();
    expect(check({ kind: "state", state: missing }).ok).toBe(false);
    expect(check({ kind: "states", state: view() }).ok).toBe(false);
    expect(check({ kind: "error" }).ok).toBe(false);
  });

  test("a call returns the parsed reply and sends the token", async () => {
    let sent: RequestInit | undefined;
    const fetcher = async (_: string, init?: RequestInit) => {
      sent = init;
      return new Response(JSON.stringify({ kind: "outside", changed: true }));
    };
    const r = await call("/api/outside", undefined, { fetcher, token: "tok" });
    expect(r).toEqual({ ok: true, value: { kind: "outside", changed: true } });
    expect(new Headers(sent?.headers).get("X-Studio-Token")).toBe("tok");
  });

  test("a network failure is an error", async () => {
    const fetcher = async () => { throw new TypeError("offline"); };
    const r = await call("/api/state", undefined, { fetcher, token: "t" });
    expect(r.ok).toBe(false);
  });

  test("a body that isn't JSON is an error", async () => {
    const fetcher = async () => new Response("<html>", { status: 403 });
    expect((await call("/api/state", undefined, { fetcher, token: "t" })).ok).toBe(false);
  });

  test("an error reply from the server is a reply, with its message", async () => {
    const r = await call("/api/undo", {}, { fetcher: ok({ kind: "error", message: "There is nothing to undo." }), token: "t" });
    expect(r).toEqual({ ok: true, value: { kind: "error", message: "There is nothing to undo." } });
  });

  test("the copied schema is the Python side's", () => {
    const python = readFileSync(new URL("../../src/policyproof/studio/api.schema.json", import.meta.url), "utf8");
    const copied = readFileSync(new URL("../src/gen/api.schema.json", import.meta.url), "utf8");
    expect(JSON.parse(copied)).toEqual(JSON.parse(python));
  });
});
