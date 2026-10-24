// The shell's side of the loop: the state plus every command not yet run. Commands are appended, never replaced,
// so messages React handles in one render (a timer and a reply landing together) all keep their commands.
import { type Cmd, init, type Msg, type State, update } from "./model";

export type Action = Msg | { kind: "Ran"; count: number };

export interface Loop {
  state: State;
  pending: readonly Cmd[];
}

export const start: Loop = { state: init, pending: [] };

export function step(loop: Loop, a: Action): Loop {
  if (a.kind === "Ran") return { ...loop, pending: loop.pending.slice(a.count) };
  const [state, cmds] = update(loop.state, a);
  return cmds.length ? { state, pending: [...loop.pending, ...cmds] } : { ...loop, state };
}
