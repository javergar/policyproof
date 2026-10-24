// The page's state and the one function that changes it (the Elm architecture): `update(state, msg)` returns the
// next state and the commands to run, as plain data. The shell in main.tsx runs the commands and feeds their
// results back as messages. Nothing here touches the network, timers or the DOM.
import type { Outcome } from "./api";
import type { Item, Option, ProposalView, ReextractView, Reply, SessionView } from "./gen/api";

export type Purpose = "state" | "change" | "undo" | "proposal" | "reword" | "reextract" | "outside";

export type Cmd =
  | { kind: "call"; path: string; body: unknown; purpose: Purpose }
  | { kind: "later"; ms: number; msg: Msg };

export type Keep = "mine" | "new";

export type Msg =
  | { kind: "Init" }
  | { kind: "Replied"; purpose: Purpose; outcome: Outcome<Reply> }
  | { kind: "Focus"; key: string }
  | { kind: "FocusSentence"; id: string }
  | { kind: "Pick"; key: string; option: number }
  | { kind: "Type"; key: string; text: string }
  | { kind: "Submit"; key: string }
  | { kind: "SubmitGroup" }
  | { kind: "Split"; keys: readonly string[] }
  | { kind: "Cancel" }
  | { kind: "Edit" }
  | { kind: "EditText"; index: number; text: string }
  | { kind: "RewordDue"; seq: number }
  | { kind: "ToggleSwitch"; name: string }
  | { kind: "Accept" }
  | { kind: "Undo" }
  | { kind: "ExtractAgain" }
  | { kind: "Keep"; index: number; which: Keep }
  | { kind: "Resolve" }
  | { kind: "CloseReextract" }
  | { kind: "Poll" }
  | { kind: "DismissError" }
  | { kind: "DismissToast" }
  | { kind: "StartField"; field: "path" | "name" | "text"; value: string }
  | { kind: "StartOpen" };

export interface Start {
  folder: string;
  model: boolean;
  message: string | null;
  path: string;
  name: string;
  text: string;
}

export interface State {
  session: SessionView | null;
  start: Start | null;
  history: readonly SessionView[]; // earlier views, so Undo shows the previous state at once
  focus: string | null;
  split: readonly string[]; // groups the author chose to decide one by one, keys joined with "+"
  picks: Readonly<Record<string, number>>;
  texts: Readonly<Record<string, string>>;
  proposal: ProposalView | null;
  switched: readonly string[];
  editing: { texts: readonly (string | null)[]; seq: number } | null;
  reextract: { view: ReextractView; keep: readonly Keep[] } | null;
  busy: boolean;
  error: string | null;
  toast: string | null;
  seq: number;
}

export const init: State = {
  session: null, start: null, history: [], focus: null, split: [], picks: {}, texts: {}, proposal: null,
  switched: [], editing: null, reextract: null, busy: false, error: null, toast: null, seq: 0,
};

export const POLL_MS = 2000;
export const REWORD_MS = 400;

export interface Unit {
  keys: string[];
  items: Item[];
}

/** The problem or group of problems the desk shows: the focused one, else the first. */
export function currentUnit(s: State): Unit | null {
  const items = s.session?.items ?? [];
  const byKey = new Map(items.map((i) => [i.key, i]));
  const placed = new Set<string>();
  const units: Unit[] = [];
  for (const item of items) {
    if (placed.has(item.key)) continue;
    const group = s.session?.groups.find((g) => g.includes(item.key));
    const together = group && !s.split.includes(group.join("+")) ? group.filter((k) => byKey.has(k)) : [item.key];
    together.forEach((k) => placed.add(k));
    units.push({ keys: together, items: together.map((k) => byKey.get(k) as Item) });
  }
  return units.find((u) => s.focus !== null && u.keys.includes(s.focus)) ?? units[0] ?? null;
}

/** An option the author has to add a sentence to before it can be sent. */
export function needsText(o: Option): boolean {
  const a = o.action;
  return (a.kind === "describe" && a.prompt !== "") || a.kind === "different" || (a.kind === "dismiss" && a.reason === null);
}

function proposes(o: Option): boolean {
  return o.action.kind === "choose" || o.action.kind === "describe" || o.action.kind === "decides";
}

const none: readonly Cmd[] = [];
const call = (path: string, body: unknown, purpose: Purpose): Cmd => ({ kind: "call", path, body, purpose });
const cleared = (s: State): State => ({ ...s, picks: {}, proposal: null, editing: null, switched: [] });

function answer(s: State, key: string, option: number): [State, readonly Cmd[]] {
  const item = s.session?.items.find((i) => i.key === key);
  const o = item?.options[option];
  if (!o) return [s, none];
  const purpose: Purpose = proposes(o) ? "proposal" : "change";
  return [{ ...s, busy: true, error: null }, [call("/api/answer", { key, option, text: s.texts[key] ?? "" }, purpose)]];
}

function replied(s: State, purpose: Purpose, outcome: Outcome<Reply>): [State, readonly Cmd[]] {
  if (!outcome.ok) return [{ ...s, busy: false, error: outcome.message }, none];
  const r = outcome.value;
  switch (r.kind) {
    case "error":
      return [{ ...s, busy: false, error: r.message },
        purpose === "undo" ? [call("/api/state", undefined, "state")] : none];
    case "start":
      return [{ ...s, busy: false, start: { folder: r.folder, model: r.model, message: r.message, path: "", name: "", text: "" } }, none];
    case "state": {
      const base = { ...cleared(s), busy: false, error: null, reextract: null, start: null, session: r.state };
      if (purpose === "state" || purpose === "undo" || s.session === null) return [base, none];
      const fresh = r.state.items.find((i) => i.new);
      return [{ ...base, history: [...s.history, s.session], focus: fresh?.key ?? null }, none];
    }
    case "proposal":
      if (purpose === "reword") return s.proposal ? [{ ...s, busy: false, proposal: r.proposal }, none] : [s, none];
      if (Object.keys(s.picks).length === 0) return [{ ...s, busy: false }, none]; // the author chose differently
      return [{ ...s, busy: false, error: null, proposal: r.proposal, switched: [], editing: null }, none];
    case "reextract":
      return [{ ...s, busy: false, reextract: { view: r.reextract, keep: r.reextract.diffs.map((d) => d.keep) } }, none];
    case "outside":
      return [s.session ? { ...s, session: { ...s.session, outside: r.changed } } : s, none];
  }
}

export function update(s: State, msg: Msg): [State, readonly Cmd[]] {
  switch (msg.kind) {
    case "Init":
      return [s, [call("/api/state", undefined, "state"), { kind: "later", ms: POLL_MS, msg: { kind: "Poll" } }]];
    case "Replied":
      return replied(s, msg.purpose, msg.outcome);
    case "Focus":
      if (!s.session?.items.some((i) => i.key === msg.key)) return [s, none];
      return [{ ...cleared(s), focus: msg.key }, none];
    case "FocusSentence": {
      const hit = s.session?.items.find((i) => i.sentences.includes(msg.id));
      return hit ? update(s, { kind: "Focus", key: hit.key }) : [s, none];
    }
    case "Pick": {
      const unit = currentUnit(s);
      const item = unit?.items.find((i) => i.key === msg.key);
      const o = item?.options[msg.option];
      if (!unit || !item || !o || s.busy) return [s, none];
      const next = { ...s, picks: { ...s.picks, [msg.key]: msg.option }, proposal: null, editing: null, error: null };
      if (needsText(o) || unit.keys.length > 1) return [next, none];
      return answer(next, msg.key, msg.option);
    }
    case "Type":
      return [{ ...s, texts: { ...s.texts, [msg.key]: msg.text } }, none];
    case "Submit": {
      const option = s.picks[msg.key];
      return option === undefined || s.busy ? [s, none] : answer(s, msg.key, option);
    }
    case "SubmitGroup": {
      const unit = currentUnit(s);
      if (!unit || unit.keys.length < 2 || s.busy || unit.keys.some((k) => s.picks[k] === undefined)) return [s, none];
      const answers = unit.keys.map((key) => ({ key, option: s.picks[key], text: s.texts[key] ?? "" }));
      return [{ ...s, busy: true, error: null }, [call("/api/group", { answers }, "proposal")]];
    }
    case "Split":
      return [{ ...cleared(s), split: [...s.split, msg.keys.join("+")], focus: msg.keys[0] ?? s.focus }, none];
    case "Cancel":
      return [{ ...cleared(s), busy: false }, none];
    case "Edit": {
      if (!s.proposal) return [s, none];
      if (s.editing) return [{ ...s, editing: null }, none];
      return [{ ...s, seq: s.seq + 1, editing: { texts: s.proposal.changes.map((c) => c.after), seq: s.seq + 1 } }, none];
    }
    case "EditText": {
      if (!s.editing || msg.index >= s.editing.texts.length || s.editing.texts[msg.index] === null) return [s, none];
      const texts = s.editing.texts.map((t, i) => (i === msg.index ? msg.text : t));
      const seq = s.seq + 1;
      return [{ ...s, seq, editing: { texts, seq } }, [{ kind: "later", ms: REWORD_MS, msg: { kind: "RewordDue", seq } }]];
    }
    case "RewordDue":
      if (!s.editing || !s.proposal || msg.seq !== s.editing.seq) return [s, none];
      return [s, [call("/api/reword", { proposal: s.proposal.id, texts: s.editing.texts }, "reword")]];
    case "ToggleSwitch": {
      const on = s.switched.includes(msg.name);
      return [{ ...s, switched: on ? s.switched.filter((n) => n !== msg.name) : [...s.switched, msg.name] }, none];
    }
    case "Accept":
      if (!s.proposal || s.busy) return [s, none];
      return [{ ...s, busy: true, error: null }, [call("/api/accept", { proposal: s.proposal.id, switch: s.switched }, "change")]];
    case "Undo": {
      const previous = s.history[s.history.length - 1];
      if (previous) {
        return [{ ...cleared(s), session: previous, history: s.history.slice(0, -1), reextract: null, busy: true, error: null },
          [call("/api/undo", {}, "undo")]];
      }
      return s.session?.can_undo ? [{ ...s, busy: true }, [call("/api/undo", {}, "undo")]] : [s, none];
    }
    case "ExtractAgain":
      return s.session ? [{ ...s, busy: true, error: null }, [call("/api/extract-again", {}, "reextract")]] : [s, none];
    case "Keep": {
      const r = s.reextract;
      if (!r || msg.index >= r.keep.length) return [s, none];
      return [{ ...s, reextract: { ...r, keep: r.keep.map((k, i) => (i === msg.index ? msg.which : k)) } }, none];
    }
    case "Resolve":
      if (!s.reextract) return [s, none];
      return [{ ...s, busy: true }, [call("/api/resolve", { reextract: s.reextract.view.id, keep: s.reextract.keep }, "change")]];
    case "CloseReextract":
      return [{ ...s, reextract: null }, none];
    case "Poll":
      return [s, [...(s.session ? [call("/api/outside", undefined, "outside")] : []),
        { kind: "later", ms: POLL_MS, msg: { kind: "Poll" } }]];
    case "DismissError":
      return [{ ...s, error: null }, none];
    case "DismissToast":
      return [{ ...s, toast: null }, none];
    case "StartField":
      return s.start ? [{ ...s, start: { ...s.start, [msg.field]: msg.value } }, none] : [s, none];
    case "StartOpen": {
      if (!s.start) return [s, none];
      const { path, name, text } = s.start;
      return [{ ...s, busy: true, error: null },
        [call("/api/start", { path: path || null, name: name || null, text: text || null }, "state")]];
    }
  }
}
