import type { SessionView } from "../gen/api";
import { currentUnit, type State } from "../model";
import { Case, Group } from "./Case";
import { type Dispatch, plural } from "./common";
import { Reextract } from "./Reextract";

function Banner({ s, dispatch, canUndo }: { s: SessionView; dispatch: Dispatch; canUndo: boolean }) {
  const b = s.banner;
  if (!b) return null;
  return (
    <div className="banner" role="status">
      <div className="what">
        {b.fixed.map((x) => <span className="fixed" key={x}>{x.includes(": ") || x.endsWith(".") ? x : `Fixed: ${x}`}</span>)}
        {b.new.map((x) => <span className="new" key={x}>New, caused by your last change: {x}</span>)}
        {b.changed.length > 0 && <span className="muted">Changed {b.changed.join(", ")} in the document.</span>}
      </div>
      {canUndo && <button className="secondary" type="button" onClick={() => dispatch({ kind: "Undo" })}>Undo</button>}
    </div>
  );
}

export function Desk({ state, dispatch }: { state: State; dispatch: Dispatch }) {
  const s = state.session;
  if (!s) return null;
  const unit = currentUnit(state);
  const others = s.items.filter((i) => !unit?.keys.includes(i.key));
  const canUndo = state.history.length > 0 || s.can_undo;
  const position = unit ? s.items.findIndex((i) => i.key === unit.keys[0]) + 1 : 0;
  return (
    <section className="desk" aria-live="polite">
      {state.error && (
        <div className="banner error" role="alert">
          <div className="what"><span>{state.error}</span></div>
          <button className="secondary" type="button" onClick={() => dispatch({ kind: "DismissError" })}>Close</button>
        </div>
      )}
      {s.outside && (
        <div className="banner caution" role="status">
          <div className="what"><span>Your document changed outside the studio. Extract it again to see what the change means for the rules.</span></div>
          <button className="secondary" type="button" disabled={!s.model || state.busy} onClick={() => dispatch({ kind: "ExtractAgain" })}>Extract again</button>
        </div>
      )}
      <Banner s={s} dispatch={dispatch} canUndo={canUndo} />
      {state.reextract ? <Reextract state={state} dispatch={dispatch} />
        : !unit ? (
          <div className="done-card">
            <h3>Every rule agrees now</h3>
            <p className="lead">Z3 checked every combination of facts the rules mention: each customer gets exactly one answer, and nothing is left to answer. {plural(s.examples.length, "example customer is", "example customers are")} approved, so a later change that alters their answer will be flagged.</p>
            <p className="lead"><b>Everything is saved</b> in {s.file}, its policy and its examples file.</p>
          </div>
        ) : unit.items.length > 1 ? <Group unit={unit} state={state} dispatch={dispatch} />
          : unit.items[0] && <Case item={unit.items[0]} position={position} total={s.items.length} state={state} dispatch={dispatch} />}
      {others.length > 0 && !state.reextract && (
        <div className="queue">
          <div className="h">Also to fix</div>
          {others.map((i) => (
            <button key={i.key} className={i.new ? "row new" : `row ${i.level}`} type="button" onClick={() => dispatch({ kind: "Focus", key: i.key })}>
              <span className="t">{i.title}</span>
              <span className="r">{i.verdicts.map((v) => v.rule).filter((r, n, a) => a.indexOf(r) === n).join(", ")}</span>
            </button>
          ))}
        </div>
      )}
      {s.examples.length > 0 && (
        <details className="saved">
          <summary>Example customers you’ve approved ({s.examples.length})</summary>
          <ul>{s.examples.map((e) => <li key={e.id}><span>{e.facts.join(", ")}</span><b>{e.outcome}</b></li>)}</ul>
        </details>
      )}
    </section>
  );
}
