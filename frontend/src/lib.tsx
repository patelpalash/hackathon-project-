export function hm(m: number) { if (m == null) return "—"; const h = Math.floor(m / 60), mm = Math.round(m % 60); return h ? `${h}h${mm ? " " + mm + "m" : ""}` : `${mm}m`; }
export function eur(n?: number | null) { return n == null ? "—" : "€" + Math.round(n).toLocaleString("en-GB"); }
export function dt(iso?: string | null) { return iso ? new Date(iso).toLocaleString("en-GB", { weekday: "short", day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit", timeZone: "Europe/Berlin", hour12: false }) : "—"; }
export function statusClass(s: string) { return "pill st-" + s.toLowerCase(); }
export function riskCls(l: string) { return "badge-risk risk-" + l; }
export function stCls(s: string) { return "badge-st st-" + s.slice(0, 2).toUpperCase().replace(/[^A-Z]/g, ""); }

export function localInput(d: Date) { return new Date(d.getTime()-d.getTimezoneOffset()*60000).toISOString().slice(0,16); }
