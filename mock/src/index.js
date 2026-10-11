// Mock of Freya Bank's statement services (service contract of 2026-10-01, section 5), serving exactly the
// answers of the bank's test environment (src/test-customers.json): same paths, envelope, status codes and bodies.
import DATA from "./test-customers.json";

const SERVICES = ["cards.list", "cards.balance", "statement.week.get", "statement.week.decide", "statement.week.change", "contact.email.get", "statement.pdf.send"];
const LOOKUP = {               // what each service is looked up by (test-customers.md)
  "cards.list": ["customerNo"],
  "cards.balance": ["cardNumber"],
  "statement.week.get": ["cardNumber"],
  "statement.week.decide": ["cardNumber", "newStatementWeek"],
  "statement.week.change": ["cardNumber", "newStatementWeek"],
  "contact.email.get": ["customerNo"],
  "statement.pdf.send": ["customerNo"],
};
const REQUIRED = {             // a missing or empty field gives 400 INVALID_ARGUMENTS_ERROR (contract section 4)
  "cards.list": ["customerNo"],
  "cards.balance": ["cardNumber"],
  "statement.week.get": ["cardNumber"],
  "statement.week.decide": ["cardNumber", "newStatementWeek", "statementDay"],
  "statement.week.change": ["cardNumber", "newStatementWeek", "statementDay"],
  "contact.email.get": ["customerNo", "intAddressInfoType"],
  "statement.pdf.send": ["customerNo", "cardNumber", "currencyType", "statementDate", "emailAddress"],
};
const NOT_FOUND = {            // the 404 of each service, where the contract has one
  "cards.list": ["FB_IVR_CHANNEL_102", "Müşteriye ait geçerli kart bilgisi bulunamadı."],
  "cards.balance": ["FB_IVR_CHANNEL_120", "Kart bilgisi bulunamadı."],
  "statement.week.get": ["FB_IVR_CHANNEL_121", "Kart bilgisi bulunamadı."],
  "statement.pdf.send": ["FB_IVR_CHANNEL_107", "Pdf dokümanı bulunamadı"],
};
const CUSTOMERS = Object.fromEntries(DATA.customers.map((c) => [String(c.customerNo), c]));
const CORS = { "Access-Control-Allow-Origin": "*" };
const LOG = [];

const json = (body, status = 200) => Response.json(body, { status, headers: CORS });
const guid = () => crypto.randomUUID().replace(/-/g, "");
const isTemplate = (v) => typeof v === "string" && (v.includes("{{") || v.startsWith("%7B%7B"));

function error(status, code, message, type) {
  const g = guid();
  return json({ result: { guid: g, returnCode: code, messageText: message, code, message, type,
    details: { guid: g, rootCause: type === "ERROR" ? "InvalidArgumentsException" : "NotFoundException", errorOrigin: "ivr-gateway-test:ivr-channel-v0" } } }, status);
}
const invalid = (field) => error(400, "INVALID_ARGUMENTS_ERROR", field + " cannot be empty", "ERROR");
function notFound(service) {
  const nf = NOT_FOUND[service];
  return nf ? error(404, nf[0], nf[1], "WARNING") : error(400, "INVALID_ARGUMENTS_ERROR", "invalid arguments", "ERROR");
}

const digits = (s) => String(s ?? "").replace(/\D/g, "");
function cardKey(table, value) {
  const v = String(value ?? "").trim();
  if (table[v]) return v;
  const d = digits(v);                         // same card written differently: first six + last four must match
  const m = Object.keys(table).filter((k) => d.length >= 10 && digits(k) === d.slice(0, 6) + d.slice(-4));
  return m.length === 1 ? m[0] : null;
}

function firstRecord(service) {                // the panel's "Test API Request" sends unfilled {{variables}}
  for (const c of DATA.customers) {
    let e = c.services[service];
    while (e && e.http === undefined) e = e[Object.keys(e)[0]];
    if (e) return e;
  }
  return null;
}

async function answer(service, data) {
  if (Object.values(data).some(isTemplate)) {
    const e = firstRecord(service);
    return e ? json(e.response, e.http) : notFound(service);
  }
  for (const f of REQUIRED[service]) {
    if (data[f] === undefined || data[f] === null || String(data[f]).trim() === "") return invalid(f);
  }
  let entry;
  if (LOOKUP[service][0] === "customerNo") {
    const c = CUSTOMERS[String(data.customerNo).trim()];
    entry = c && c.services[service];
  } else {
    let table = null;
    for (const c of DATA.customers) {
      const t = c.services[service];
      if (t && cardKey(t, data.cardNumber)) { table = t; break; }
    }
    entry = table && table[cardKey(table, data.cardNumber)];
    if (entry && LOOKUP[service][1]) entry = entry[String(data.newStatementWeek).trim()];
  }
  if (!entry) return notFound(service);
  const delay = entry.delaySeconds ?? entry.gecikmeSaniye;
  if (delay) await new Promise((r) => setTimeout(r, delay * 1000));
  return json(entry.response ?? entry.yanit, entry.http);
}

async function handle(request) {
  const url = new URL(request.url);
  if (request.method === "OPTIONS") return new Response(null, { headers: { ...CORS, "Access-Control-Allow-Methods": "GET, POST, OPTIONS", "Access-Control-Allow-Headers": "*" } });
  const path = url.pathname.replace(/\/+$/, "");
  if (path === "/health" || path === "/_health") return json({ durum: "ok", customers: DATA.customers.length });
  if (path === "/_log") return json(LOG.slice(-300));
  const service = SERVICES.find((s) => path === "/voice/v1/" + s || path === "/" + s);
  if (!service) return json({ hata: "bulunamadı", yollar: SERVICES.map((s) => "POST /voice/v1/" + s) }, 404);
  let body = {};
  try { body = await request.json(); } catch { body = {}; }
  const data = body && typeof body.data === "object" && body.data ? body.data : body;   // envelope {data, call}
  return answer(service, data || {});
}

export default {
  async fetch(request) {
    const copy = request.clone();
    const res = await handle(request);
    let body = null;
    try { body = await copy.json(); } catch { body = null; }
    LOG.push({ t: new Date().toISOString(), path: new URL(request.url).pathname, body, status: res.status });
    if (LOG.length > 1000) LOG.splice(0, LOG.length - 1000);
    return res;
  },
};
