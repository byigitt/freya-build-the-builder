"""Build a Freya phone agent from a bank's collections brief.

    python3 builder/build.py <brief.md> [more brief files ...] <tool_api.json>

Steps (all logged to stdout and to traces/<slot>-<time>.log):
  1. extract: a strong model turns the brief into a spec (builder/spec_guide.md), reviews it rule by rule, a checker validates it
  2. self-test the spec's policy code locally on synthetic customers (dates, amounts, persuasion, outcomes)
  3. compile the spec and the tool API into a workflow (builder/compile.py), dry-run validate, save in place, publish
  4. smoke-test the published agent over chat (it starts, says the opening line)
  5. export the workflow to submission/<slot>.workflow.json
Needs FREYA_API_KEY and AI_GATEWAY_API_KEY (or LLM_BASE_URL + LLM_API_KEY for another OpenAI-compatible endpoint).
"""
import datetime, importlib.util, json, os, pathlib, sys, time, traceback

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path[:0] = [str(HERE), str(ROOT)]
import freya
import llm
from compile import compile_workflow, audit, POLICY_SRC
from extract import extract


class Trace:
    def __init__(self, path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self.f = path.open("w")

    def __call__(self, msg):
        line = time.strftime("%Y-%m-%dT%H:%M:%S") + " " + msg
        print(line, flush=True)
        self.f.write(line + "\n")
        self.f.flush()


def policy_selftest(spec, trace):
    """Run the in-call policy code locally on synthetic customers built from the spec. Returns the number of problems."""
    mod = importlib.util.module_from_spec(importlib.util.spec_from_loader("pol", loader=None))
    exec(POLICY_SRC, mod.__dict__)
    mod.CFG = spec
    acc = spec.get("account", {})
    types = list((acc.get("types") or {}).items())
    now = "2026-10-14T11:00"
    problems = 0
    for days_late in sorted({int(b.get("min_days", 1)) for b in spec.get("bands", [])} | {int(b.get("max_days", 30)) for b in spec.get("bands", []) if b.get("max_days")}):
        prods = []
        for i, (t, ts) in enumerate(types[:3]):
            p = {acc.get("id_field", "product_id"): "p%d" % (i + 1), acc.get("type_field", "type"): t, acc.get("amount_field", "past_due"): 400.0 + 100 * i,
                 acc.get("days_late_field", "days_late"): days_late}
            if ts.get("floor_field"):
                p[ts["floor_field"]] = 120.0 + 10 * i
            for ph in ("card_last4", "last4", "account_last4"):
                if "<" + ph + ">" in (ts.get("words") or ""):
                    p[ph] = "1234"
            prods.append(p)
        for n in (1, len(prods)):
            v = {spec.get("variables", {}).get("now", "now"): now}
            for i, p in enumerate(prods[:n]):
                for k, val in p.items():
                    v["load_account_response.data.%s.%d.%s" % (acc.get("products_field", "products"), i, k)] = str(val)
            mod.run_prepare(v)
            st = json.loads(v.get("pol_state") or "null")
            if not st or v.get("account_state") != "ok":
                trace("  self-test FAIL prepare days_late=%d n=%d: %s" % (days_late, n, v.get("account_state")))
                problems += 1
                continue
            for _ in range(30):                                     # refuse everything: every product must end refused
                if v.get("policy_phase") != "negotiating":
                    break
                cur = [p for p in st["products"] if p["status"] in ("open", "offered")]
                mod.run_assess(v, dict(event="refuse", product=cur[0]["id"]))
                st = json.loads(v["pol_state"])
            mod.run_finalize(v)
            bad = "error" in str(v.get("next_instruction", "")) or v.get("finalize_error") or v.get("policy_phase") != "done"
            trace("  self-test refuse-all days_late=%d products=%d: phase=%s outcome=%s/%s attempts=%s%s" % (
                days_late, n, v.get("policy_phase"), v.get("final_outcome"), v.get("final_reason"),
                [p["attempts_used"] for p in st["products"]], " PROBLEM" if bad else ""))
            problems += 1 if bad else 0
            v2 = {k: val for k, val in v.items() if k.startswith("load_account_response") or k == spec.get("variables", {}).get("now", "now")}
            mod.run_prepare(v2)
            mod.run_assess(v2, dict(event="propose", product="all" if n > 1 else "p1", date="2026-11-30"))
            mod.run_assess(v2, dict(event="accept_offer", product="all" if n > 1 else "p1"))
            for _ in range(4):
                if v2.get("policy_phase") != "negotiating":
                    break
                stt = json.loads(v2["pol_state"])
                cur = [p for p in stt["products"] if p["status"] in ("open", "offered")]
                mod.run_assess(v2, dict(event="accept_offer", product=cur[0]["id"]))
            mod.run_commit_check(v2)
            dates = [v2.get("c%d_date" % k) for k in (1, 2, 3) if v2.get("c%d_go" % k) == "yes"]
            ok = v2.get("commit_ready") == "yes" and dates and all(d and d <= "2026-11-30" for d in dates)
            trace("  self-test late-date days_late=%d products=%d: commit_ready=%s dates=%s%s" % (days_late, n, v2.get("commit_ready"), dates, "" if ok else " PROBLEM"))
            problems += 0 if ok else 1
    return problems


def chat_smoke(workflow_id, spec, trace):
    vars_ = {}
    for role, name in (spec.get("variables") or {}).items():
        vars_[name] = {"customer_id": "c_smoke_test", "now": "2026-10-14T11:00", "title": "Mr", "first_name": "Alex", "last_name": "Smoke"}.get(role, "Test")
    try:
        r = freya.api("POST", "/api/v2/chat/message", {"workflowId": workflow_id, "message": "Hello?", "customerVariables": vars_})
        said = (r.get("response") or "").strip()
        trace("  chat smoke test: agent said: " + said[:200])
        try:
            freya.api("POST", "/api/v2/chat/end", {"callId": r.get("callId")})
        except Exception:
            pass
        return bool(said)
    except Exception as e:
        trace("  chat smoke test failed: " + str(e)[:300])
        return False


def main(argv):
    if len(argv) < 2:
        sys.exit(__doc__)
    brief_paths, api_path = argv[:-1], argv[-1]
    slot = "-".join(pathlib.Path(p).stem for p in brief_paths)
    start = datetime.datetime.now(datetime.timezone.utc)
    trace = Trace(ROOT / "traces" / (slot + "-" + start.strftime("%Y%m%d-%H%M%S") + ".log"))
    trace("BUILD START " + start.isoformat() + " briefs=" + ", ".join(brief_paths) + " tool_api=" + api_path)
    brief = "\n\n".join(pathlib.Path(p).read_text() for p in brief_paths)
    openapi = json.load(open(api_path))
    spent0 = llm.spent()

    trace("step 1: extract the spec from the brief (model " + __import__("extract").MODEL + ")")
    spec = extract(brief, openapi, trace)
    out = ROOT / "out"
    out.mkdir(exist_ok=True)
    (out / (slot + ".spec.json")).write_text(json.dumps(spec, indent=1))
    trace("  spec saved to out/" + slot + ".spec.json; coverage lines: " + str(len(spec.get("coverage", []))))
    for c in spec.get("coverage", []):
        trace("    coverage: " + str(c)[:200])

    trace("step 2: self-test the policy code on synthetic customers")
    problems = policy_selftest(spec, trace)
    trace("  self-test problems: " + str(problems))

    trace("step 3: compile, validate, save and publish")
    wf = compile_workflow(spec, openapi)
    issues = audit(wf, openapi)
    trace("  bank-call audit: " + ("; ".join(issues) if issues else "every bank call sends the fields the tool API requires"))
    (out / (slot + ".workflow.json")).write_text(json.dumps(wf, indent=1))
    freya.validate_workflow(slot, wf)
    trace("  dry-run validation passed: %d steps, %d tools, %d bytes" % (len(wf["nodes"]), sum(len(n.get("tools", [])) + len(n.get("pre_actions", [])) for n in wf["nodes"].values()), len(json.dumps(wf))))
    state = str(ROOT / ".freya-agents.json")
    try:
        ids = freya.save_workflow(slot, wf, state_file=state)
    except RuntimeError as e:                       # a state file from another workspace: start a fresh workflow for this slot
        trace("  update failed (" + str(e)[:160] + "), creating a new workflow for slot " + slot)
        st = json.loads(pathlib.Path(state).read_text()) if pathlib.Path(state).exists() else {}
        st.pop(slot, None)
        pathlib.Path(state).write_text(json.dumps(st, indent=1))
        ids = freya.save_workflow(slot, wf, state_file=state)
    if "version" not in ids:
        ids = freya.save_workflow(slot, wf, state_file=state)
    trace("  saved and published: workflow_id=%s agent_id=%s version=%s" % (ids["workflow_id"], ids["agent_id"], ids.get("version")))

    trace("step 4: chat smoke test of the published agent")
    chat_smoke(ids["workflow_id"], spec, trace)

    trace("step 5: export")
    sub = ROOT / "submission"
    sub.mkdir(exist_ok=True)
    path = freya.export_workflow(ids["workflow_id"], str(sub / (slot + ".workflow.json")))
    trace("  exported to " + path)
    end = datetime.datetime.now(datetime.timezone.utc)
    trace("BUILD END " + end.isoformat() + " duration=%.0fs model_spend=$%.2f workflow_id=%s agent_id=%s" % (
        (end - start).total_seconds(), llm.spent() - spent0, ids["workflow_id"], ids["agent_id"]))
    print(json.dumps({"workflow_id": ids["workflow_id"], "agent_id": ids["agent_id"], "export": path}))


if __name__ == "__main__":
    try:
        main(sys.argv[1:])
    except Exception:
        traceback.print_exc()
        sys.exit(1)
