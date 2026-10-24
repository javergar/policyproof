// A small session view for the page's tests: the couriers policy with its two clashes.
import type { Item, ProposalView, SessionView } from "../src/gen/api";

export const clash = (key: string, title: string, extra: Partial<Item> = {}): Item => ({
  key,
  kind: "clash",
  level: "error",
  title,
  facts: ["Came by courier", "1 day late", "Asked for a refund"],
  lead: "Two rules give opposite answers for this customer:",
  verdicts: [
    { rule: "Rule 1", sentence: "Courier parcels are never refunded.", says: "Nothing", tone: "no" },
    { rule: "Rule 2", sentence: "A late courier parcel is refunded if the customer asks.", says: "A refund", tone: "yes" },
  ],
  note: null,
  question: "What should this customer get?",
  options: [
    { label: "A refund", action: { kind: "choose", outcome: "refund" }, secondary: false },
    { label: "Nothing", action: { kind: "choose", outcome: "nothing" }, secondary: false },
    { label: "Something else…", action: { kind: "describe", prompt: "What should this customer get?", prefix: "This customer should get: " }, secondary: false },
    { label: "A voucher", action: { kind: "choose", outcome: "voucher" }, secondary: true },
    { label: "It depends on something else…", action: { kind: "describe", prompt: "What does it depend on?", prefix: "It depends: " }, secondary: false },
  ],
  sentences: ["s1", "s2"],
  logic: ["Rule 1 (C4):  carrier = COURIER → ¬refund"],
  new: false,
  dismissed_before: null,
  ...extra,
});

export const LATE = clash("clash:C4+C5", "A late courier parcel, the customer asked");
export const LOST = clash("clash:C4+C6", "A lost courier parcel", {
  facts: ["Came by courier", "The parcel was lost"],
  verdicts: [
    { rule: "Rule 1", sentence: "Courier parcels are never refunded.", says: "Nothing", tone: "no" },
    { rule: "Rule 3", sentence: "Lost parcels are always refunded.", says: "A refund", tone: "yes" },
  ],
  sentences: ["s1", "s3"],
});
export const CONSTRAINT: Item = {
  key: "constraint:C9", kind: "constraint", level: "review", title: "“Days late are never negative.”", facts: [],
  lead: "Rule 5, read as: this, and only this.", verdicts: [], note: null, question: "Is that exactly right?",
  options: [
    { label: "Yes, exactly", action: { kind: "dismiss", reason: "Exactly right" }, secondary: false },
    { label: "No", action: { kind: "describe", prompt: "What's wrong with it?", prefix: "This sentence isn't quite right: " }, secondary: false },
  ],
  sentences: ["s5"], logic: [], new: false, dismissed_before: null,
};

export const view = (over: Partial<SessionView> = {}): SessionView => ({
  file: "couriers.md",
  doc: {
    file: "couriers.md",
    rules: 5,
    sections: [
      { level: 1, heading: "Couriers policy", sentences: [{ id: "s0", text: "What courier customers get.", number: null, state: "uncovered", was: null }] },
      {
        level: 2, heading: "Couriers", sentences: [
          { id: "s1", text: "Courier parcels are never refunded.", number: 1, state: "open", was: null },
          { id: "s2", text: "A late courier parcel is refunded if the customer asks.", number: 2, state: "plain", was: null },
          { id: "s3", text: "Lost parcels are always refunded.", number: 3, state: "plain", was: null },
        ],
      },
      { level: 2, heading: "Post", sentences: [{ id: "s5", text: "Days late are never negative.", number: 5, state: "plain", was: null }] },
    ],
  },
  items: [LATE, LOST, CONSTRAINT],
  groups: [["clash:C4+C5", "clash:C4+C6"]],
  open: 3,
  fixed: 0,
  examples: [],
  banner: null,
  can_undo: false,
  model: true,
  outside: false,
  done: false,
  version: 0,
  ...over,
});

export const proposal = (over: Partial<ProposalView> = {}): ProposalView => ({
  id: "p1",
  changes: [{ kind: "replace", section: "Couriers", before: "Courier parcels are never refunded.", after: "Courier parcels are never refunded, unless they arrive late and the customer asks." }],
  checks: [{ tone: "ok", text: "Fixes “A late courier parcel”." }, { tone: "ok", text: "Checked against every rule: nothing new conflicts." }],
  additions: [],
  switches: [],
  risky: false,
  attempts: 1,
  ...over,
});
