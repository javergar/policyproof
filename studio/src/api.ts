// Talking to the studio's server. Every reply is checked against the API's JSON Schema before the state sees it,
// so a page and a server that disagree show an error instead of half a state.
import Ajv from "ajv";
import type { Reply } from "./gen/api";
import schema from "./gen/api.schema.json";

export type Outcome<T> = { ok: true; value: T } | { ok: false; message: string };

const ajv = new Ajv({ strict: false, allErrors: false });
ajv.addSchema(schema, "api");
const validate = ajv.getSchema<Reply>("api#/$defs/Reply");

export function check(data: unknown): Outcome<Reply> {
  if (validate === undefined) return { ok: false, message: "The page has no schema for the server's replies." };
  if (validate(data)) return { ok: true, value: data as Reply };
  const first = validate.errors?.[0];
  return { ok: false, message: `The server sent something this page doesn't understand (${first?.instancePath || "reply"} ${first?.message ?? ""}). Reload the page.` };
}

export type Fetcher = (url: string, init?: RequestInit) => Promise<Response>;

export function pageToken(): string {
  const meta = document.querySelector<HTMLMetaElement>('meta[name="studio-token"]');
  return meta?.content ?? new URLSearchParams(location.search).get("t") ?? "";
}

export async function call(path: string, body: unknown, opts: { fetcher?: Fetcher; token: string }): Promise<Outcome<Reply>> {
  const fetcher = opts.fetcher ?? ((url, init) => fetch(url, init));
  let response: Response;
  try {
    response = await fetcher(path, {
      method: body === undefined ? "GET" : "POST",
      headers: { "X-Studio-Token": opts.token, ...(body === undefined ? {} : { "Content-Type": "application/json" }) },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    });
  } catch {
    return { ok: false, message: "The studio isn't answering. Is it still running?" };
  }
  let data: unknown;
  try {
    data = await response.json();
  } catch {
    return { ok: false, message: response.status === 403 ? "This page needs the link the studio printed when it started." : `The studio answered ${response.status} without a reply.` };
  }
  return check(data);
}
