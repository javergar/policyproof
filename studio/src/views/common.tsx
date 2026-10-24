import { words } from "../diff";
import type { Msg } from "../model";

export type Dispatch = (msg: Msg) => void;

/** A sentence with what changed in it marked, or the sentence as it is. */
export function Words({ was, now }: { was: string | null; now: string | null }) {
  if (was === now || (was === null && now === null)) return <>{now}</>;
  const parts = words(was, now);
  return (
    <>
      {parts.map((p, i) => {
        const space = i > 0 ? " " : "";
        if (p.kind === "del") return <span key={i}>{space}<del>{p.text}</del></span>;
        if (p.kind === "ins") return <span key={i}>{space}<ins>{p.text}</ins></span>;
        return <span key={i}>{space}{p.text}</span>;
      })}
    </>
  );
}

export const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;
