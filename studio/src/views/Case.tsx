import type { Item, Option, Verdict } from "../gen/api";
import { needsText, type State, type Unit } from "../model";
import type { Dispatch } from "./common";
import { ProposalPanel } from "./Proposal";

const EYEBROW: Record<Item["level"], string> = {
  error: "Problem", uncovered: "A sentence to check", warning: "To answer", review: "To review",
};

function VerdictCard({ v, shared }: { v: Verdict; shared: boolean }) {
  return (
    <div className={shared ? "verdict shared" : "verdict"}>
      <span className="who">{v.rule}{shared ? " · in every one of these" : ""}</span>
      {v.says && <span className={`says ${v.tone}`}>{v.says}</span>}
      <q>{v.sentence}</q>
    </div>
  );
}

function Logic({ lines }: { lines: string[] }) {
  if (lines.length === 0) return null;
  return (
    <details className="logic">
      <summary>Show the logic</summary>
      <pre>{lines.join("\n")}</pre>
    </details>
  );
}

function promptOf(o: Option): string {
  const a = o.action;
  if (a.kind === "describe" || a.kind === "different") return a.prompt;
  return "Why? The reason is kept with it.";
}

function submitLabel(o: Option): string {
  return o.action.kind === "describe" ? "Propose a change" : "Save";
}

/** The answers to one item; the picked one pressed, and its sentence box when it needs one. */
function Choices({ item, state, dispatch, inGroup }: { item: Item; state: State; dispatch: Dispatch; inGroup: boolean }) {
  const picked = state.picks[item.key];
  const option = picked === undefined ? undefined : item.options[picked];
  const elsewhere = option?.action.kind === "describe" && option.action.prefix.startsWith("This customer should get");
  const shown = item.options.map((o, i) => [o, i] as const).filter(([o]) => !o.secondary || elsewhere);
  const id = `text-${item.key}`;
  return (
    <>
      <div className="choices">
        {shown.map(([o, i]) => (
          <button key={i} type="button" className={o.secondary ? "choice quiet" : "choice"} aria-pressed={picked === i}
            disabled={state.busy} onClick={() => dispatch({ kind: "Pick", key: item.key, option: i })}>{o.label}</button>
        ))}
      </div>
      {option && needsText(option) && (
        <div className="depends">
          <label htmlFor={id}>{promptOf(option)}</label>
          <input type="text" id={id} value={state.texts[item.key] ?? ""}
            onChange={(e) => dispatch({ kind: "Type", key: item.key, text: e.target.value })}
            onKeyDown={(e) => { if (e.key === "Enter" && !inGroup) dispatch({ kind: "Submit", key: item.key }); }} />
          {!inGroup && (
            <div className="actions">
              <button className="primary" type="button" disabled={state.busy || !(state.texts[item.key] ?? "").trim()}
                onClick={() => dispatch({ kind: "Submit", key: item.key })}>{submitLabel(option)}</button>
            </div>
          )}
        </div>
      )}
    </>
  );
}

export function Case({ item, position, total, state, dispatch }: {
  item: Item; position: number; total: number; state: State; dispatch: Dispatch;
}) {
  return (
    <article className="case">
      <div className="case-head">
        <div className={item.new ? "eyebrow new" : `eyebrow ${item.level}`}>
          {item.new ? <>New problem <span className="tag">caused by your last change</span></>
            : item.level === "error" ? `Problem ${position} of ${total}` : EYEBROW[item.level]}
        </div>
        <h3>{item.title}</h3>
        {item.facts.length > 0 && <div className="facts">{item.facts.map((f) => <span className="fact" key={f}>{f}</span>)}</div>}
      </div>
      <div className="case-body">
        {item.dismissed_before && (
          <p className="note">You dismissed this before: “{item.dismissed_before}”. The rules it involves have changed since, so it’s back.</p>
        )}
        {item.lead && <p className="lead">{item.lead}</p>}
        {item.verdicts.length > 0 && (
          <div className="verdicts">{item.verdicts.map((v, i) => <VerdictCard key={i} v={v} shared={false} />)}</div>
        )}
        {item.note && <p className="note">{item.note}</p>}
        {item.question ? (
          <div className="ask">
            <div className="q">{item.question}</div>
            <Choices item={item} state={state} dispatch={dispatch} inGroup={false} />
          </div>
        ) : (
          <p className="note">There is nothing to answer here: the check couldn’t finish, so it can’t count as passing. Simplifying the rules involved, or splitting them up, usually helps.</p>
        )}
        {state.busy && !state.proposal && <p className="lead busy">Checking the change against every rule…</p>}
        {state.proposal && <ProposalPanel p={state.proposal} state={state} dispatch={dispatch} />}
        <Logic lines={item.logic} />
      </div>
    </article>
  );
}

export function Group({ unit, state, dispatch }: { unit: Unit; state: State; dispatch: Dispatch }) {
  const sharedRules = unit.items[0]?.verdicts.map((v) => v.rule)
    .filter((r) => unit.items.every((i) => i.verdicts.some((v) => v.rule === r))) ?? [];
  const ready = unit.keys.every((k) => state.picks[k] !== undefined);
  return (
    <article className="case">
      <div className="case-head">
        <div className="eyebrow">{unit.items.length} problems that share {sharedRules.join(", ") || "rules"}</div>
        <h3>One decision can settle {unit.items.length === 2 ? "both" : "all of them"}</h3>
      </div>
      <div className="case-body">
        {unit.items.map((item) => (
          <div className="ask member" key={item.key}>
            <div className="q">{item.title}</div>
            {item.facts.length > 0 && <div className="facts">{item.facts.map((f) => <span className="fact" key={f}>{f}</span>)}</div>}
            <div className="verdicts">{item.verdicts.map((v, i) => <VerdictCard key={i} v={v} shared={sharedRules.includes(v.rule)} />)}</div>
            <div className="q small">{item.question}</div>
            <Choices item={item} state={state} dispatch={dispatch} inGroup={true} />
          </div>
        ))}
        <p className="note">Answer each customer and we’ll propose one change to {sharedRules.join(", ") || "the rules"} for all of them. If you’d rather think about them one at a time, decide each separately.</p>
        {!state.proposal && (
          <div className="actions">
            <button className="primary" type="button" disabled={!ready || state.busy} onClick={() => dispatch({ kind: "SubmitGroup" })}>
              Propose one change for all of them
            </button>
            <button className="choice quiet" type="button" onClick={() => dispatch({ kind: "Split", keys: unit.keys })}>Decide each one separately</button>
          </div>
        )}
        {state.busy && !state.proposal && <p className="lead busy">Checking the change against every rule…</p>}
        {state.proposal && <ProposalPanel p={state.proposal} state={state} dispatch={dispatch} />}
        <Logic lines={unit.items.flatMap((i) => i.logic)} />
      </div>
    </article>
  );
}
