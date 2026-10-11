// Rehearsal routes for the synthetic fake case contract (lab/fake-case/services.md).
const cust = (customers, body) => customers[String(body.customer_id || "").trim()];
const rec = (records, id) => (records[id] ||= { verify: [], promises: [], notes: [], callbacks: [], transfers: [], closes: [] });

export const ROUTES = {
  "/kimlik-dogrula": async ({ body, customers, records }) => {
    const c = cust(customers, body);
    if (!c) return { status: 404, body: { verified: false, error: "unknown customer" } };
    const ok = String(c.identity[body.field] ?? "").trim() === String(body.answer ?? "").trim();
    rec(records, body.customer_id).verify.push({ field: body.field, answer: body.answer, ok });
    return { verified: ok };
  },
  "/hesap-getir": async ({ body, customers }) => {
    const c = cust(customers, body);
    return c ? c.account : { status: 404, body: { error: "unknown customer" } };
  },
  "/odeme-sozu-olustur": async ({ body, records }) => {
    const r = rec(records, body.customer_id);
    r.promises.push({ statement_id: body.statement_id, amount: Number(body.amount), date: body.date });
    return { success: true, promise_id: "pr" + r.promises.length };
  },
  "/not-ekle": async ({ body, records }) => { rec(records, body.customer_id).notes.push(body); return { success: true }; },
  "/geri-arama": async ({ body, records }) => { rec(records, body.customer_id).callbacks.push(body); return { success: true }; },
  "/temsilciye-aktar": async ({ body, records }) => { rec(records, body.customer_id).transfers.push(body); return { success: true }; },
  "/aramayi-bitir": async ({ body, records }) => { rec(records, body.customer_id).closes.push(body); return { success: true }; },
};
