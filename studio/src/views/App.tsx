import { currentUnit, type State } from "../model";
import type { Dispatch } from "./common";
import { Desk } from "./Desk";
import { Doc } from "./Doc";

function Bar({ state, dispatch }: { state: State; dispatch: Dispatch }) {
  const s = state.session;
  return (
    <header className="bar">
      <div className="brand"><b>Policyproof Studio</b>{s && <span>{s.file}</span>}</div>
      {s && (
        <div className="status">
          {s.open > 0 ? <span className="pill bad">{s.open} {s.open === 1 ? "thing" : "things"} to fix</span>
            : <span className="pill good">Every rule agrees</span>}
          <span className="pill">{s.fixed} fixed</span>
          <span className="pill">{s.examples.length} example {s.examples.length === 1 ? "customer" : "customers"}</span>
        </div>
      )}
      {s && (
        <>
          <button className="tool" type="button" disabled={state.busy || !(state.history.length > 0 || s.can_undo)} onClick={() => dispatch({ kind: "Undo" })}>Undo</button>
          <button className="tool" type="button" disabled={state.busy || !s.model} title={s.model ? undefined : "Start the studio with --model to extract again"}
            onClick={() => dispatch({ kind: "ExtractAgain" })}>Extract again</button>
        </>
      )}
    </header>
  );
}

function Start({ state, dispatch }: { state: State; dispatch: Dispatch }) {
  const st = state.start;
  if (!st) return null;
  return (
    <div className="start case">
      <div className="case-head"><h3>Open a policy document</h3></div>
      <div className="case-body">
        {st.message && <p className="note">{st.message}</p>}
        {!st.model && <p className="lead">A document that has no policy yet needs a model to extract it: start the studio with --model.</p>}
        <div className="depends">
          <label htmlFor="path">A markdown file in {st.folder}</label>
          <input id="path" type="text" placeholder="delivery-refunds.md" value={st.path} onChange={(e) => dispatch({ kind: "StartField", field: "path", value: e.target.value })} />
        </div>
        <p className="lead">Or paste one:</p>
        <div className="depends">
          <label htmlFor="name">File name</label>
          <input id="name" type="text" placeholder="delivery-refunds" value={st.name} onChange={(e) => dispatch({ kind: "StartField", field: "name", value: e.target.value })} />
          <label htmlFor="text">The policy, in markdown</label>
          <textarea id="text" rows={12} value={st.text} onChange={(e) => dispatch({ kind: "StartField", field: "text", value: e.target.value })} />
        </div>
        {state.error && <p className="note">{state.error}</p>}
        <div className="actions">
          <button className="primary" type="button" disabled={state.busy || !(st.path || (st.name && st.text))} onClick={() => dispatch({ kind: "StartOpen" })}>Open</button>
        </div>
      </div>
    </div>
  );
}

export function App({ state, dispatch }: { state: State; dispatch: Dispatch }) {
  const s = state.session;
  const unit = currentUnit(state);
  const focus = new Set(unit?.items.flatMap((i) => i.sentences) ?? []);
  return (
    <div className="wrap">
      <Bar state={state} dispatch={dispatch} />
      {s ? (
        <div className="grid">
          <Doc doc={s.doc} focus={focus} dispatch={dispatch} />
          <Desk state={state} dispatch={dispatch} />
        </div>
      ) : state.start ? <Start state={state} dispatch={dispatch} />
        : <p className="lead">{state.error ?? "Opening the studio…"}</p>}
    </div>
  );
}
