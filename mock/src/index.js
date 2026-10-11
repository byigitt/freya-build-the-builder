// Mock of the bank's services for the final case. Endpoints are filled in from the case's service contract.
// All state lives in one Durable Object so every request sees the same records.
import { DurableObject } from "cloudflare:workers";
import { CUSTOMERS } from "./customers.js";
import { ROUTES } from "./routes.js";

const json = (body, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json; charset=utf-8" } });

export class Bank extends DurableObject {
  async fetch(request) {
    const url = new URL(request.url);
    const path = url.pathname.replace(/\/+$/, "") || "/";
    let body = {};
    if (request.method !== "GET") {
      try { body = await request.json(); } catch { body = {}; }
    } else {
      body = Object.fromEntries(url.searchParams);
    }
    const store = this.ctx.storage;
    if (path === "/_health") return json({ ok: true, customers: Object.keys(CUSTOMERS).length });
    if (path === "/_log") return json((await store.get("log")) || []);
    if (path === "/_records") return json((await store.get("records")) || {});
    if (path === "/_reset" && request.method === "POST") { await store.deleteAll(); return json({ ok: true }); }
    const handler = ROUTES[path];
    let status = 200, out;
    if (!handler) { status = 404; out = { ok: false, error: "unknown endpoint " + path }; }
    else {
      try {
        const records = (await store.get("records")) || {};
        const res = await handler({ body, customers: CUSTOMERS, records, now: new Date() });
        out = res.body ?? res; status = res.status ?? 200;
        await store.put("records", records);
      } catch (e) { status = 500; out = { ok: false, error: String(e) }; }
    }
    const log = (await store.get("log")) || [];
    log.push({ t: new Date().toISOString(), path, body, status, out });
    await store.put("log", log.slice(-500));
    return json(out, status);
  }
}

export default {
  async fetch(request, env) {
    const stub = env.BANK.get(env.BANK.idFromName("bank"));
    return stub.fetch(request);
  },
};
