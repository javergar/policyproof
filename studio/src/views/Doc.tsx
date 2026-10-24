import type { DocView, SentenceView } from "../gen/api";
import { type Dispatch, Words } from "./common";

function Sentence({ s, focused, dispatch }: { s: SentenceView; focused: boolean; dispatch: Dispatch }) {
  const text = s.state === "removed" ? <del>{s.text}</del> : s.state === "inserted" ? <ins>{s.text}</ins>
    : s.was !== null ? <Words was={s.was} now={s.text} /> : s.text;
  const open = () => dispatch({ kind: "FocusSentence", id: s.id });
  return (
    <li className="sentence" id={s.id} tabIndex={0} data-state={s.state} data-focus={focused} onClick={open}
      onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); open(); } }}>
      <span className="num">{s.number ?? ""}</span>
      <span className="txt">{text}</span>
    </li>
  );
}

export function Doc({ doc, focus, dispatch }: { doc: DocView; focus: ReadonlySet<string>; dispatch: Dispatch }) {
  return (
    <article className="sheet" aria-label="Policy document">
      <div className="file">{doc.file} · {doc.rules} {doc.rules === 1 ? "rule" : "rules"} extracted</div>
      {doc.sections.map((sec, i) => (
        <section key={`${i}-${sec.heading}`}>
          {sec.level === 1 ? <h1>{sec.heading}</h1> : sec.heading ? <h2>{sec.heading}</h2> : null}
          {sec.sentences.length > 0 && (
            <ol className="clauses">
              {sec.sentences.map((s) => <Sentence key={s.id} s={s} focused={focus.has(s.id)} dispatch={dispatch} />)}
            </ol>
          )}
        </section>
      ))}
    </article>
  );
}
