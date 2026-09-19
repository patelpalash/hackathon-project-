import type { components } from "./schema";
import { demoApi } from "./demoApi";
// FastAPI serializes defaulted response fields too (arrays and nulls are present).
type Serialized<T> = T extends (infer I)[]
  ? Serialized<I>[]
  : T extends object
    ? { [K in keyof T]-?: Serialized<Exclude<T[K], undefined>> }
    : T;
export type Model<K extends keyof components["schemas"]> = Serialized<
  components["schemas"][K]
>;
export type Route = Model<"Route">;
export type Network = Model<"Network">;
export type State = Model<"State">;
export type Event = Model<"Event">;
export type Plan = Model<"PlanView">;
export async function api<T>(
  path: string,
  body?: unknown,
  method = "POST",
  signal?: AbortSignal,
): Promise<T> {
  try {
    const response = await fetch(`${import.meta.env.VITE_API_BASE || "/api"}${path}`, {
      method: body === undefined ? "GET" : method,
      headers: { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal,
    });
    const text = await response.text();
    const data = text ? JSON.parse(text) : {};
    if (!response.ok)
      throw new Error(
        `${response.status === 409 ? "Conditions changed. Refresh and review before submitting. " : ""}${data.error?.message || "Request failed"}`,
      );
    return data;
  } catch (error) {
    if (signal?.aborted) throw error;
    if (import.meta.env.VITE_API_BASE) throw error;
    return demoApi<T>(path, body, method);
  }
}
export const intent = () => crypto.randomUUID();
export const duration = (minutes: number) =>
  `${Math.floor(minutes / 60)}h${minutes % 60 ? ` ${minutes % 60}m` : ""}`;
export const stamp = (iso: string, zone = "Europe/Berlin") =>
  new Intl.DateTimeFormat("en-GB", {
    timeZone: zone,
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
    timeZoneName: "short",
  }).format(new Date(iso));
