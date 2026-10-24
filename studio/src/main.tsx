// The shell around the pure loop: one useReducer holds the state and the commands not yet run; an effect runs them
// and their results come back as messages.
import { useEffect, useReducer } from "react";
import { createRoot } from "react-dom/client";
import { call, pageToken } from "./api";
import { start, step } from "./loop";
import type { Cmd, Msg } from "./model";
import "./styles.css";
import { App } from "./views/App";

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
  const [loop, dispatch] = useReducer(step, start);
  useEffect(() => dispatch({ kind: "Init" }), []);
  useEffect(() => {
    if (loop.pending.length === 0) return;
    const todo = loop.pending;
    dispatch({ kind: "Ran", count: todo.length });
    for (const c of todo) run(c, dispatch);
  }, [loop.pending]);
  return <App state={loop.state} dispatch={dispatch} />;
}

const root = document.getElementById("root");
if (root) createRoot(root).render(<Studio />);
