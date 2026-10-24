import fc from "fast-check";
import { describe, expect, test } from "vitest";
import type { Reply, SessionView } from "../src/gen/api";
import { init, update, type Msg, type State } from "../src/model";
import { CONSTRAINT, LATE, LOST, proposal, view } from "./sample";

const ok = (value: Reply) => ({ ok: true as const, value });
const run = (s: State, msgs: Msg[]) => msgs.reduce((acc, m) => update(acc, m)[0], s);
const loaded = run(init, [{ kind: "Replied", purpose: "state", outcome: ok({ kind: "state", state: view() }) }]);

const sessions: fc.Arbitrary<SessionView> = fc.record({
  version: fc.nat(20), items: fc.subarray([LATE, LOST, CONSTRAINT]), can_undo: fc.boolean(),
}).map(({ version, items, can_undo }) => view({ version, items, can_undo, groups: [] }));

const keys = fc.constantFrom(LATE.key, LOST.key, CONSTRAINT.key, "gone");
const msgs: fc.Arbitrary<Msg> = fc.oneof(
  keys.map((key): Msg => ({ kind: "Focus", key })),
  fc.record({ key: keys, option: fc.nat(6) }).map(({ key, option }): Msg => ({ kind: "Pick", key, option })),
  fc.record({ key: keys, text: fc.string() }).map(({ key, text }): Msg => ({ kind: "Type", key, text })),
  keys.map((key): Msg => ({ kind: "Submit", key })),
  fc.constant<Msg>({ kind: "SubmitGroup" }),
  fc.constant<Msg>({ kind: "Cancel" }),
  fc.constant<Msg>({ kind: "Accept" }),
  fc.constant<Msg>({ kind: "Undo" }),
  fc.constant<Msg>({ kind: "Edit" }),
  fc.record({ index: fc.nat(2), text: fc.string() }).map(({ index, text }): Msg => ({ kind: "EditText", index, text })),
  fc.nat(5).map((seq): Msg => ({ kind: "RewordDue", seq })),
  fc.constant<Msg>({ kind: "Split", keys: [LATE.key, LOST.key] }),
  fc.constant<Msg>({ kind: "Poll" }),
  fc.constant<Msg>({ kind: "ExtractAgain" }),
  fc.constant<Msg>({ kind: "Resolve" }),
  fc.constant<Msg>({ kind: "DismissToast" }),
  sessions.map((state): Msg => ({ kind: "Replied", purpose: "change", outcome: ok({ kind: "state", state }) })),
  fc.constant<Msg>({ kind: "Replied", purpose: "proposal", outcome: ok({ kind: "proposal", proposal: proposal() }) }),
  fc.constant<Msg>({ kind: "Replied", purpose: "change", outcome: ok({ kind: "error", message: "no" }) }),
  fc.constant<Msg>({ kind: "Replied", purpose: "change", outcome: { ok: false, message: "garbled" } }),
);

describe("laws of update", () => {
  test("undo after any accepted change restores the session before it", () => {
    fc.assert(fc.property(fc.array(msgs, { maxLength: 12 }), sessions, (before, next) => {
      const s = run(loaded, before);
      fc.pre(s.session !== null);
      const accepted = run(s, [{ kind: "Replied", purpose: "change", outcome: ok({ kind: "state", state: next }) }]);
      const undone = run(accepted, [{ kind: "Undo" }]);
      expect(undone.session).toBe(s.session);
    }));
  });

  test("cancel after a pick returns to the state before it", () => {
    fc.assert(fc.property(fc.array(msgs, { maxLength: 12 }), keys, fc.nat(4), (before, key, option) => {
      const s = run(loaded, [...before, { kind: "Cancel" }]);
      const back = run(s, [{ kind: "Pick", key, option }, { kind: "Cancel" }]);
      expect({ picks: back.picks, proposal: back.proposal, editing: back.editing })
        .toEqual({ picks: s.picks, proposal: s.proposal, editing: s.editing });
    }));
  });

  test("update never throws and never loses the session", () => {
    fc.assert(fc.property(fc.array(msgs, { maxLength: 30 }), (all) => {
      const s = run(loaded, all);
      expect(s.session).not.toBeNull();
    }));
  });

  test("a reword timer from an older edit does nothing", () => {
    fc.assert(fc.property(fc.array(msgs, { maxLength: 12 }), fc.nat(5), (before, stale) => {
      const s = run(loaded, before);
      fc.pre(s.editing === null || stale !== s.editing.seq);
      const [after, cmds] = update(s, { kind: "RewordDue", seq: stale });
      expect(after).toBe(s);
      expect(cmds).toEqual([]);
    }));
  });
});
