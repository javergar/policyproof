import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, test } from "vitest";
import type { Reply } from "../src/gen/api";
import { init, update, type Msg, type State } from "../src/model";
import { App } from "../src/views/App";
import { CONSTRAINT, LATE, LOST, proposal, view } from "./sample";

const ok = (value: Reply) => ({ ok: true as const, value });
const run = (s: State, msgs: Msg[]) => msgs.reduce((acc, m) => update(acc, m)[0], s);
const loaded = (v = view()) => run(init, [{ kind: "Replied", purpose: "state", outcome: ok({ kind: "state", state: v }) }]);
const html = (s: State) => renderToStaticMarkup(<App state={s} dispatch={() => {}} />);
const single = (v = view()) => run(loaded(v), [{ kind: "Split", keys: [LATE.key, LOST.key] }]);
const withoutLogic = (markup: string) => markup.replace(/<details class="logic">.*?<\/details>/gs, "");

describe("the views", () => {
  test("the document marks open sentences and shows tracked changes", () => {
    const v = view();
    const changed = { ...v, doc: { ...v.doc, sections: v.doc.sections.map((sec) => ({ ...sec, sentences: sec.sentences.map((x) =>
      x.id === "s2" ? { ...x, state: "changed" as const, was: "A late courier parcel is refunded." } : x) })) } };
    const out = html(loaded(changed));
    expect(out).toContain('data-state="open"');
    expect(out).toContain('data-state="changed"');
    expect(out).toContain("<del>refunded.</del>");
    expect(out).toContain("<ins>refunded if the customer asks.</ins>");
    expect(out).toContain("couriers.md · 5 rules extracted");
  });

  test("a clash shows what each rule says and the choices", () => {
    const out = html(single());
    expect(out).toContain("A late courier parcel, the customer asked");
    expect(out).toContain("Two rules give opposite answers for this customer:");
    expect(out).toContain("Courier parcels are never refunded.");
    expect(out).toContain(">A refund</button>");
    expect(out).toContain("It depends on something else…");
    expect(out).not.toContain(">A voucher</button>"); // under "Something else…" until it is picked
    expect(out).toContain("Problem 1 of 3");
  });

  test("something else shows the other outcomes and a sentence box", () => {
    const out = html(run(single(), [{ kind: "Pick", key: LATE.key, option: 2 }]));
    expect(out).toContain(">A voucher</button>");
    expect(out).toContain("What should this customer get?</label>");
  });

  test("a proposal shows the change, the checks, and Accept anyway when risky", () => {
    const picked = run(single(), [{ kind: "Pick", key: LATE.key, option: 0 }]);
    const calm = html(run(picked, [{ kind: "Replied", purpose: "proposal", outcome: ok({ kind: "proposal", proposal: proposal() }) }]));
    expect(calm).toContain("The change we’d make");
    expect(calm).toContain("<ins>refunded, unless they arrive late and the customer asks.</ins>");
    expect(calm).toContain(">Accept</button>");
    const risky = proposal({ risky: true, checks: [{ tone: "warn", text: "This wording causes a new problem." }],
      additions: ["The agent will now ask customers: Was it insured?"], switches: [{ var: "insured", label: "Was it insured?", role: "ask" }] });
    const out = html(run(picked, [{ kind: "Replied", purpose: "proposal", outcome: ok({ kind: "proposal", proposal: risky }) }]));
    expect(out).toContain(">Accept anyway</button>");
    expect(out).toContain('class="check warn"');
    expect(out).toContain("The agent will now ask customers: Was it insured?");
    expect(out).toContain("The agent asks the customer");
  });

  test("editing the wording shows a box per changed sentence", () => {
    const s = run(single(), [{ kind: "Pick", key: LATE.key, option: 0 },
      { kind: "Replied", purpose: "proposal", outcome: ok({ kind: "proposal", proposal: proposal() }) }, { kind: "Edit" }]);
    const out = html(s);
    expect(out).toContain("<textarea");
    expect(out).toContain(">Done editing</button>");
  });

  test("a group shows each customer and a way to decide them one by one", () => {
    const out = html(loaded());
    expect(out).toContain("2 problems that share Rule 1");
    expect(out).toContain("A late courier parcel, the customer asked");
    expect(out).toContain("A lost courier parcel");
    expect(out).toContain("Decide each one separately");
    expect(out).toContain("Propose one change for all of them");
  });

  test("the rest of the problems wait in a queue", () => {
    const out = html(single());
    expect(out).toContain("Also to fix");
    expect(out).toContain(CONSTRAINT.title.replace(/“|”/g, (q) => q));
  });

  test("the done card says everything is saved", () => {
    const out = html(loaded(view({ items: [], groups: [], open: 0, done: true, fixed: 2,
      examples: [{ id: "e1", facts: ["Came by courier"], outcome: "A refund" }] })));
    expect(out).toContain("Everything is saved");
    expect(out).toContain("Every rule agrees");
    expect(out).toContain("Example customers you’ve approved (1)");
  });

  test("the last change is shown with undo", () => {
    const out = html(loaded(view({ banner: { fixed: ["A late courier parcel"], new: ["A lost courier parcel"], changed: ["Rule 1"] }, can_undo: true })));
    expect(out).toContain("Fixed: A late courier parcel");
    expect(out).toContain("New, caused by your last change: A lost courier parcel");
  });

  test("an outside edit offers to extract again", () => {
    expect(html(loaded(view({ outside: true })))).toContain("Your document changed outside the studio");
  });

  test("extracting again lists each changed sentence with a choice", () => {
    const reextract = { id: "r1", diffs: [{ sentence: "Courier parcels are never refunded.", section: "Couriers", mine: ["a"], new: ["b"], mine_said: ["Never refunded."], new_said: ["Refunded when lost."], hand_fixed: true, keep: "mine" as const }] };
    const out = html(run(loaded(), [{ kind: "Replied", purpose: "reextract", outcome: ok({ kind: "reextract", reextract }) }]));
    expect(out).toContain("Keep mine");
    expect(out).toContain("Use the new reading");
    expect(out).toContain("You fixed this one");
    expect(out).toContain("Refunded when lost.");
  });

  test("no formula reaches the page outside the logic", () => {
    for (const s of [single(), loaded()]) expect(withoutLogic(html(s))).not.toMatch(/→|¬|∧|unsat|witness/);
  });

  test("without a document the page asks for one", () => {
    const s = run(init, [{ kind: "Replied", purpose: "state", outcome: ok({ kind: "start", folder: "/docs", model: false, message: "no policy" }) }]);
    const out = html(s);
    expect(out).toContain("Open a policy document");
    expect(out).toContain("no policy");
    expect(out).toContain("--model");
  });
});
