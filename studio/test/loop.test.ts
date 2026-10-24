import { describe, expect, test } from "vitest";
import { start, step } from "../src/loop";

describe("the shell's command queue (final review I2)", () => {
  test("commands from messages handled in one render are all kept until run", () => {
    let loop = step(start, { kind: "Init" });
    loop = step(loop, { kind: "Poll" });
    expect(loop.pending.map((c) => (c.kind === "call" ? c.path : c.kind))).toEqual(["/api/state", "later", "later"]);
    loop = step(loop, { kind: "Ran", count: 2 });
    expect(loop.pending).toHaveLength(1);
  });
});
