// The shell around the pure loop: one useReducer holds the state, and an effect runs the commands each update
// returns, turning their results back into messages.
import { useEffect, useReducer } from "react";
import { createRoot } from "react-dom/client";
import { call, pageToken } from "./api";
import { type Cmd, init, type Msg, type State, update } from "./model";
import "./styles.css";
import { App } from "./views/App";

type Loop = { state: State; cmds: readonly Cmd[]; n: number };

function step(loop: Loop, msg: Msg): Loop {
  const [state, cmds] = update(loop.state, msg);
  return { state, cmds, n: loop.n + 1 };
}

const token = pageToken();

function run(cmd: Cmd, dispatch: (m: Msg) => void): void {
  switch (cmd.kind) {
    case "call":
      void call(cmd.path, cmd.body, { token }).then((outcome) => dispatch({ kind: "Replied", purpose: cmd.purpose, outcome }));
      return;
    case "later":
      setTimeout(() => dispatch(cmd.msg), cmd.ms);
      return;
  }
}

function Studio() {
  const [loop, dispatch] = useReducer(step, { state: init, cmds: [], n: 0 });
  useEffect(() => dispatch({ kind: "Init" }), []);
  useEffect(() => { for (const c of loop.cmds) run(c, dispatch); }, [loop.n]); // eslint-disable-line react-hooks/exhaustive-deps
  return <App state={loop.state} dispatch={dispatch} />;
}

const root = document.getElementById("root");
if (root) createRoot(root).render(<Studio />);
