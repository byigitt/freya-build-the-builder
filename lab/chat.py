"""Compile+deploy a spec, or run a scripted chat against a deployed slot.

    python3 lab/chat.py deploy <slot> <spec.json> [openapi.json]
    python3 lab/chat.py run <slot> <case_id> "msg 1" "msg 2" ...
"""
import json, pathlib, sys, time
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "tools"), str(ROOT / "builder")]
import freya
from score import http
from compile import compile_workflow


def deploy(slot, spec_path, oa_path=str(ROOT / "tools/openapi.json")):
    wf = compile_workflow(json.load(open(spec_path)), json.load(open(oa_path)))
    pathlib.Path(ROOT / "out").mkdir(exist_ok=True)
    (ROOT / "out" / (slot + ".workflow.json")).write_text(json.dumps(wf, indent=1))
    freya.validate_workflow(slot, wf)
    r = freya.save_workflow(slot, wf, state_file=str(ROOT / ".freya-agents.json"))
    if "version" not in r:                       # first save creates; update once so the event model is set and published
        r = freya.save_workflow(slot, wf, state_file=str(ROOT / ".freya-agents.json"))
    print(json.dumps(r))
    return r


def run(slot, case_id, msgs):
    wid = json.load(open(ROOT / ".freya-agents.json"))[slot]["workflow_id"]
    s = http("/v1/practice/sessions", {"case": case_id})["variables"]
    cid = None
    for m in msgs:
        b = {"workflowId": wid, "message": m}
        if cid:
            b["callId"] = cid
        else:
            b["customerVariables"] = s
        out = freya.api("POST", "/api/v2/chat/message", b)
        cid = out.get("callId") or cid
        print(">>", m, "\n<<", out.get("response"), flush=True)
    led = http("/v1/practice/ledger/" + s["customer_id"])
    print("LEDGER", json.dumps({k: led.get(k) for k in ("outcome", "reason", "promises", "notes", "callbacks", "transfers")}))
    print("TOOLS", [(c["tool"], c.get("args"), c.get("result")) for c in led.get("calls", [])])
    print("CALL", cid)


if __name__ == "__main__":
    if sys.argv[1] == "deploy":
        deploy(*sys.argv[2:])
    else:
        run(sys.argv[2], sys.argv[3], sys.argv[4:])
