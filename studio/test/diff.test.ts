import fc from "fast-check";
import { describe, expect, test } from "vitest";
import { words } from "../src/diff";

const text = (parts: { kind: string; text: string }[], keep: string) =>
  parts.filter((p) => p.kind === "same" || p.kind === keep).map((p) => p.text).join(" ").split(" ").filter(Boolean).join(" ");

describe("word diff", () => {
  test("marks only the words that changed", () => {
    expect(words("Courier parcels are never refunded.", "Courier parcels are never refunded, unless lost.")).toEqual([
      { kind: "same", text: "Courier parcels are never" },
      { kind: "del", text: "refunded." },
      { kind: "ins", text: "refunded, unless lost." },
    ]);
  });

  test("a new or removed sentence is all one part", () => {
    expect(words(null, "New.")).toEqual([{ kind: "ins", text: "New." }]);
    expect(words("Old.", null)).toEqual([{ kind: "del", text: "Old." }]);
  });

  test("law: the parts keep both sentences", () => {
    const sentence = fc.array(fc.constantFrom("a", "b", "c", "refund", "never"), { maxLength: 8 }).map((ws) => ws.join(" "));
    fc.assert(fc.property(sentence, sentence, (a, b) => {
      const parts = words(a, b);
      expect(text(parts, "del")).toBe(a.split(" ").filter(Boolean).join(" "));
      expect(text(parts, "ins")).toBe(b.split(" ").filter(Boolean).join(" "));
    }));
  });
});
