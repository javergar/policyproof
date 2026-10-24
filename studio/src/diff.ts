// The word diff the page shows for a changed sentence: the common words before and after, and what changed between.
export type Part = { kind: "same" | "del" | "ins"; text: string };

export function words(a: string | null, b: string | null): Part[] {
  if (a === null) return b ? [{ kind: "ins", text: b }] : [];
  if (b === null) return a ? [{ kind: "del", text: a }] : [];
  const x = a.split(" ").filter(Boolean);
  const y = b.split(" ").filter(Boolean);
  let i = 0;
  while (i < x.length && i < y.length && x[i] === y[i]) i++;
  let j = 0;
  while (j < x.length - i && j < y.length - i && x[x.length - 1 - j] === y[y.length - 1 - j]) j++;
  const parts: Part[] = [
    { kind: "same", text: x.slice(0, i).join(" ") },
    { kind: "del", text: x.slice(i, x.length - j).join(" ") },
    { kind: "ins", text: y.slice(i, y.length - j).join(" ") },
    { kind: "same", text: x.slice(x.length - j).join(" ") },
  ];
  return parts.filter((p) => p.text);
}
