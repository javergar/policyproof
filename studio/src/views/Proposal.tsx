import type { ProposalView } from "../gen/api";
import type { State } from "../model";
import { type Dispatch, Words } from "./common";

function heading(kind: "replace" | "insert" | "remove", section: string) {
  if (kind === "remove") return "Remove this sentence";
  if (kind === "insert") return section ? `New sentence in “${section}”` : "New sentence";
  return "This sentence becomes";
}

export function ProposalPanel({ p, state, dispatch }: { p: ProposalView; state: State; dispatch: Dispatch }) {
  const editing = state.editing;
  return (
    <div className="proposal">
      <div className="h">The change we’d make</div>
      {p.changes.map((c, i) => (
        <div className="change" key={i}>
          <span className="rid">{heading(c.kind, c.section)}</span>
          {editing && c.after !== null ? (
            <textarea aria-label={`Wording for change ${i + 1}`} value={editing.texts[i] ?? ""}
              onChange={(e) => dispatch({ kind: "EditText", index: i, text: e.target.value })} />
          ) : (
            <div className="after"><Words was={c.before} now={c.after} /></div>
          )}
        </div>
      ))}
      {p.additions.length > 0 && (
        <div className="additions">
          {p.additions.map((a) => <div className="addition" key={a}>{a}</div>)}
          {p.switches.map((sw) => {
            const flipped = state.switched.includes(sw.var);
            const asks = (sw.role === "ask") !== flipped;
            return (
              <div className="switch" key={sw.var}>
                <span>{sw.label}:</span>
                <button type="button" className="choice" aria-pressed={asks} onClick={() => { if (!asks) dispatch({ kind: "ToggleSwitch", name: sw.var }); }}>The agent asks the customer</button>
                <button type="button" className="choice" aria-pressed={!asks} onClick={() => { if (asks) dispatch({ kind: "ToggleSwitch", name: sw.var }); }}>It comes from your systems</button>
              </div>
            );
          })}
        </div>
      )}
      <div className="checks">
        {p.checks.map((c, i) => <div key={i} className={c.tone === "ok" ? "check" : `check ${c.tone}`}>{c.text}</div>)}
        {p.attempts > 1 && <div className="check open">This took {p.attempts} tries to get right.</div>}
      </div>
      <div className="actions">
        <button className={p.risky ? "primary risky" : "primary"} type="button" disabled={state.busy}
          onClick={() => dispatch({ kind: "Accept" })}>{p.risky ? "Accept anyway" : "Accept"}</button>
        {p.changes.some((c) => c.after !== null) && (
          <button className="secondary" type="button" onClick={() => dispatch({ kind: "Edit" })}>
            {editing ? "Done editing" : "Edit the wording"}
          </button>
        )}
        <button className="secondary" type="button" onClick={() => dispatch({ kind: "Cancel" })}>Choose differently</button>
      </div>
    </div>
  );
}
