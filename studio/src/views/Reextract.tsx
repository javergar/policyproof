import type { State } from "../model";
import type { Dispatch } from "./common";

export function Reextract({ state, dispatch }: { state: State; dispatch: Dispatch }) {
  const r = state.reextract;
  if (!r) return null;
  return (
    <article className="case">
      <div className="case-head">
        <div className="eyebrow plain">Extracted again</div>
        <h3>{r.view.diffs.length === 0 ? "Nothing reads differently" : `${r.view.diffs.length} ${r.view.diffs.length === 1 ? "sentence reads" : "sentences read"} differently now`}</h3>
      </div>
      <div className="case-body">
        <p className="lead">For each one, keep the rules you have or use the new reading of the sentence. Sentences you fixed are set to keep yours.</p>
        {r.view.diffs.map((d, i) => (
          <div className="ask member" key={i}>
            <div className="verdict"><span className="who">{d.section}{d.hand_fixed ? " · You fixed this one" : ""}</span><q>{d.sentence}</q></div>
            {(d.mine_said.length > 0 || d.new_said.length > 0) ? (
              <div className="verdicts">
                <div className="verdict"><span className="who">Your rules say</span><span>{d.mine_said.join(" ") || "Nothing: no rule comes from it now."}</span></div>
                <div className="verdict"><span className="who">The new reading says</span><span>{d.new_said.join(" ") || "Nothing: no rule would come from it."}</span></div>
              </div>
            ) : <p className="lead">The two readings differ; start the studio with a model to see them in words.</p>}
            <div className="choices">
              <button type="button" className="choice" aria-pressed={r.keep[i] === "mine"} onClick={() => dispatch({ kind: "Keep", index: i, which: "mine" })}>Keep mine</button>
              <button type="button" className="choice" aria-pressed={r.keep[i] === "new"} onClick={() => dispatch({ kind: "Keep", index: i, which: "new" })}>Use the new reading</button>
            </div>
            <details className="logic">
              <summary>Show the logic</summary>
              <pre>{["Yours:", ...d.mine.map((x) => `  ${x}`), "New reading:", ...d.new.map((x) => `  ${x}`)].join("\n")}</pre>
            </details>
          </div>
        ))}
        <div className="actions">
          <button className="primary" type="button" disabled={state.busy} onClick={() => dispatch({ kind: "Resolve" })}>Apply</button>
          <button className="secondary" type="button" onClick={() => dispatch({ kind: "CloseReextract" })}>Cancel</button>
        </div>
      </div>
    </article>
  );
}
