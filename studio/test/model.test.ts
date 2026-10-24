import { describe, expect, test } from "vitest";
import type { Reply } from "../src/gen/api";
import { currentUnit, init, update, type Cmd, type Msg, type State } from "../src/model";
import { CONSTRAINT, LATE, LOST, proposal, view } from "./sample";

const ok = (value: Reply) => ({ ok: true as const, value });
const step = (s: State, ...msgs: Msg[]): [State, Cmd[]] => {
  let cmds: Cmd[] = [];
  for (const m of msgs) {
    const [next, c] = update(s, m);
    s = next;
    cmds = [...c];
  }
  return [s, cmds];
};
const loaded = (v = view()) => step(init, { kind: "Replied", purpose: "state", outcome: ok({ kind: "state", state: v }) })[0];
const calls = (cmds: readonly Cmd[]) => cmds.flatMap((c) => (c.kind === "call" ? [[c.path, c.body]] : []));

describe("the update loop", () => {
  test("init asks for the state and starts polling", () => {
    const [, cmds] = update(init, { kind: "Init" });
    expect(calls(cmds)).toEqual([["/api/state", undefined]]);
    expect(cmds.some((c) => c.kind === "later")).toBe(true);
  });

  test("a group is the first unit until it is split", () => {
    const s = loaded();
    expect(currentUnit(s)?.keys).toEqual([LATE.key, LOST.key]);
    const [split] = step(s, { kind: "Split", keys: [LATE.key, LOST.key] });
    expect(currentUnit(split)?.keys).toEqual([LATE.key]);
    const [focused] = step(split, { kind: "Focus", key: LOST.key });
    expect(currentUnit(focused)?.keys).toEqual([LOST.key]);
  });

  test("picking an outcome on a single item proposes it", () => {
    const [s] = step(loaded(), { kind: "Split", keys: [LATE.key, LOST.key] });
    const [after, cmds] = step(s, { kind: "Pick", key: LATE.key, option: 0 });
    expect(after.picks[LATE.key]).toBe(0);
    expect(after.busy).toBe(true);
    expect(calls(cmds)).toEqual([["/api/answer", { key: LATE.key, option: 0, text: "" }]]);
  });

  test("an option that needs a sentence waits for it", () => {
    const [s] = step(loaded(), { kind: "Split", keys: [LATE.key, LOST.key] });
    const [picked, none] = step(s, { kind: "Pick", key: LATE.key, option: 4 });
    expect(calls(none)).toEqual([]);
    const [, cmds] = step(picked, { kind: "Type", key: LATE.key, text: "only if late" }, { kind: "Submit", key: LATE.key });
    expect(calls(cmds)).toEqual([["/api/answer", { key: LATE.key, option: 4, text: "only if late" }]]);
  });

  test("a group is proposed once every customer has an answer", () => {
    const [s, none] = step(loaded(), { kind: "Pick", key: LATE.key, option: 0 });
    expect(calls(none)).toEqual([]);
    const [, cmds] = step(s, { kind: "Pick", key: LOST.key, option: 1 }, { kind: "SubmitGroup" });
    expect(calls(cmds)).toEqual([["/api/group", { answers: [{ key: LATE.key, option: 0, text: "" }, { key: LOST.key, option: 1, text: "" }] }]]);
  });

  test("a proposal arrives, is accepted, and the new state replaces the old with history", () => {
    const [s] = step(loaded(), { kind: "Split", keys: [LATE.key, LOST.key] }, { kind: "Pick", key: LATE.key, option: 0 },
      { kind: "Replied", purpose: "proposal", outcome: ok({ kind: "proposal", proposal: proposal() }) });
    expect(s.proposal?.id).toBe("p1");
    const [accepting, cmds] = step(s, { kind: "Accept" });
    expect(calls(cmds)).toEqual([["/api/accept", { proposal: "p1", switch: [] }]]);
    const next = view({ items: [LOST, CONSTRAINT], version: 1, can_undo: true });
    const [done] = step(accepting, { kind: "Replied", purpose: "change", outcome: ok({ kind: "state", state: next }) });
    expect(done.session).toBe(next);
    expect(done.history).toHaveLength(1);
    expect(done.proposal).toBeNull();
    expect(done.picks).toEqual({});
  });

  test("an error reply is shown and clears the busy flag", () => {
    const [s] = step(loaded(), { kind: "Split", keys: [LATE.key, LOST.key] }, { kind: "Pick", key: LATE.key, option: 0 },
      { kind: "Replied", purpose: "proposal", outcome: ok({ kind: "error", message: "Start the studio with --model to propose changes." }) });
    expect(s.error).toContain("--model");
    expect(s.busy).toBe(false);
  });

  test("a reply the page can't read is an error, and the session stays", () => {
    const s = loaded();
    const [after] = step(s, { kind: "Replied", purpose: "change", outcome: { ok: false, message: "bad reply" } });
    expect(after.error).toBe("bad reply");
    expect(after.session).toBe(s.session);
  });

  test("editing the wording is debounced and checked", () => {
    const [s] = step(loaded(), { kind: "Split", keys: [LATE.key, LOST.key] }, { kind: "Pick", key: LATE.key, option: 0 },
      { kind: "Replied", purpose: "proposal", outcome: ok({ kind: "proposal", proposal: proposal() }) }, { kind: "Edit" });
    expect(s.editing?.texts).toEqual(["Courier parcels are never refunded, unless they arrive late and the customer asks."]);
    const [typed, later] = step(s, { kind: "EditText", index: 0, text: "Courier parcels are refunded when late." });
    expect(later).toEqual([{ kind: "later", ms: 400, msg: { kind: "RewordDue", seq: typed.editing?.seq } }]);
    const [, cmds] = step(typed, { kind: "RewordDue", seq: typed.editing?.seq ?? -1 });
    expect(calls(cmds)).toEqual([["/api/reword", { proposal: "p1", texts: ["Courier parcels are refunded when late."] }]]);
  });

  test("clicking a sentence focuses its problem", () => {
    const [s] = step(loaded(), { kind: "Split", keys: [LATE.key, LOST.key] }, { kind: "FocusSentence", id: "s3" });
    expect(currentUnit(s)?.keys).toEqual([LOST.key]);
  });

  test("polling notices an outside edit", () => {
    const [s, cmds] = step(loaded(), { kind: "Poll" });
    expect(calls(cmds)).toEqual([["/api/outside", undefined]]);
    const [after] = step(s, { kind: "Replied", purpose: "outside", outcome: ok({ kind: "outside", changed: true }) });
    expect(after.session?.outside).toBe(true);
  });

  test("extract again lists the diffs and resolves with the author's choices", () => {
    const reextract = { id: "r1", diffs: [{ sentence: "a", section: "Couriers", mine: ["x"], new: ["y"], mine_said: ["Never refunded."], new_said: ["Refunded when lost."], hand_fixed: true, keep: "mine" as const }] };
    const [s] = step(loaded(), { kind: "ExtractAgain" },
      { kind: "Replied", purpose: "reextract", outcome: ok({ kind: "reextract", reextract }) });
    expect(s.reextract?.keep).toEqual(["mine"]);
    const [, cmds] = step(s, { kind: "Keep", index: 0, which: "new" }, { kind: "Resolve" });
    expect(calls(cmds)).toEqual([["/api/resolve", { reextract: "r1", keep: ["new"] }]]);
  });

  test("without a document the page asks for one", () => {
    const [s] = step(init, { kind: "Replied", purpose: "state", outcome: ok({ kind: "start", folder: "/docs", model: true, message: null }) });
    expect(s.start?.folder).toBe("/docs");
    const [, cmds] = step(s, { kind: "StartField", field: "name", value: "refunds" }, { kind: "StartField", field: "text", value: "# R" },
      { kind: "StartOpen" });
    expect(calls(cmds)).toEqual([["/api/start", { path: null, name: "refunds", text: "# R" }]]);
  });
});

describe("rewording (final review I1)", () => {
  const editing = () => step(loaded(), { kind: "Split", keys: [LATE.key, LOST.key] }, { kind: "Pick", key: LATE.key, option: 0 },
    { kind: "Replied", purpose: "proposal", outcome: ok({ kind: "proposal", proposal: proposal() }) }, { kind: "Edit" })[0];

  test("accept waits while the author's wording is being checked", () => {
    const [typed] = step(editing(), { kind: "EditText", index: 0, text: "Mine." });
    const [, none] = step(typed, { kind: "Accept" });
    expect(calls(none)).toEqual([]);
    const [sent] = step(typed, { kind: "RewordDue", seq: typed.editing?.seq ?? -1 });
    expect(calls(step(sent, { kind: "Accept" })[1])).toEqual([]);
    const [back] = step(sent, { kind: "Replied", purpose: "reword", outcome: ok({ kind: "proposal", proposal: proposal({ id: "p2" }) }) });
    expect(calls(step(back, { kind: "Accept" })[1])).toEqual([["/api/accept", { proposal: "p2", switch: [] }]]);
  });

  test("one check at a time, and the latest wording is checked last", () => {
    let [s] = step(editing(), { kind: "EditText", index: 0, text: "First." });
    [s] = step(s, { kind: "RewordDue", seq: s.editing?.seq ?? -1 });
    [s] = step(s, { kind: "EditText", index: 0, text: "Second." });
    const [waiting, none] = step(s, { kind: "RewordDue", seq: s.editing?.seq ?? -1 });
    expect(calls(none)).toEqual([]);
    const [, again] = step(waiting, { kind: "Replied", purpose: "reword", outcome: ok({ kind: "proposal", proposal: proposal({ id: "p2" }) }) });
    expect(calls(again)).toEqual([["/api/reword", { proposal: "p2", texts: ["Second."] }]]);
  });
});
