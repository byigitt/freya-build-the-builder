// Mock of the bank's statement services for the final case, served from the bank's own test data
// (src/test-customers.json: per customer, per service, per card (and week) the exact HTTP status and body).
import DATA from "./test-customers.json";

const SERVICES = ["cards.list", "cards.balance", "statement.week.get", "statement.week.decide", "statement.week.change", "contact.email.get", "statement.pdf.send"];
const norm = (s) => String(s || "").toLowerCase().replace(/[^a-z0-9]/g, "");
const BY_NORM = Object.fromEntries(SERVICES.map((s) => [norm(s), s]));
const CUSTOMERS = Object.fromEntries(DATA.customers.map((c) => [String(c.customerNo), c]));
const LOG = [];

const json = (body, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json; charset=utf-8" } });

function serviceOf(path) {
  const p = norm(path);
  if (BY_NORM[p]) return BY_NORM[p];
  // longest service name contained in the path (e.g. /api/v1/statement/week/decide)
  const hit = SERVICES.filter((s) => p.endsWith(norm(s)) || p.includes(norm(s))).sort((a, b) => b.length - a.length)[0];
  return hit || null;
}

function flat(obj, out = {}) {
  for (const [k, v] of Object.entries(obj || {})) {
    if (v && typeof v === "object" && !Array.isArray(v)) flat(v, out);
    else out[k] = v;
  }
  return out;
}

function findCustomer(f) {
  for (const [k, v] of Object.entries(f)) if (/cust|musteri|müşteri/i.test(k) && CUSTOMERS[String(v).trim()]) return CUSTOMERS[String(v).trim()];
  for (const v of Object.values(f)) if (CUSTOMERS[String(v).trim()]) return CUSTOMERS[String(v).trim()];
  return null;
}

function pickKey(table, f, prefer) {
  const keys = Object.keys(table || {});
  const vals = Object.entries(f).filter(([k]) => !prefer || prefer.test(k)).map(([, v]) => String(v ?? "").replace(/\s/g, ""));
  for (const v of vals) if (keys.includes(v)) return v;                                  // exact (masked) card number
  const digits = (s) => s.replace(/\D/g, "");
  for (const v of vals) {                                                                   // same last digits
    const d = digits(v);
    if (d.length >= 4) {
      const m = keys.filter((k) => digits(k).endsWith(d.slice(-4)) && (d.length < 10 || digits(k).startsWith(d.slice(0, 6))));
      if (m.length === 1) return m[0];
    }
  }
  return null;
}

async function handle(request) {
  const url = new URL(request.url);
  const path = url.pathname.replace(/\/+$/, "") || "/";
  if (path === "/_health") return json({ ok: true, customers: Object.keys(CUSTOMERS).length });
  if (path === "/_log") return json(LOG.slice(-300));
  let body = {};
  if (request.method !== "GET") { try { body = await request.json(); } catch { body = {}; } }
  for (const [k, v] of url.searchParams) body[k] = v;
  const service = serviceOf(path);
  if (!service) return json({ error: "unknown service " + path }, 404);
  const f = flat(body);
  const cust = findCustomer(f);
  if (!cust) return json({ data: null, result: { returnCode: "0", messageText: "Customer not found", code: "0", message: "Customer not found" } }, 404);
  let entry = cust.services[service];
  if (!entry) return json({ data: null, result: { returnCode: "0", messageText: "No data for this customer", code: "0", message: "No data" } }, 404);
  if (entry.http === undefined) {
    const card = pickKey(entry, f, /card|kart/i) || pickKey(entry, f);
    if (!card) return json({ data: null, result: { returnCode: "0", messageText: "Card not found", code: "0", message: "Card not found" } }, 404);
    entry = entry[card];
    if (entry.http === undefined) {
      const wk = Object.entries(f).find(([k]) => /week|hafta/i.test(k));
      const w = wk ? String(wk[1]).replace(/\D/g, "") : "";
      entry = entry[w];
      if (!entry) return json({ data: null, result: { returnCode: "0", messageText: "Week not available", code: "0", message: "Week not available" } }, 400);
    }
  }
  if (entry.gecikmeSaniye) await new Promise((r) => setTimeout(r, entry.gecikmeSaniye * 1000));
  return json(entry.response ?? entry.yanit ?? {}, entry.http || 200);
}

export default {
  async fetch(request) {
    const res = await handle(request.clone());
    try {
      let body = null;
      try { body = await request.json(); } catch { body = null; }
      LOG.push({ t: new Date().toISOString(), path: new URL(request.url).pathname, body, status: res.status });
      if (LOG.length > 1000) LOG.splice(0, LOG.length - 1000);
    } catch {}
    return res;
  },
};
