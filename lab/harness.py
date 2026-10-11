"""Local, parallel stand-in for tools/run_cases.py.

Drives the published workflow over POST /api/v2/chat/message, plays the customer with gemini-3-flash (the model the
official simulation uses) and judges the transcript with the same success criteria. Bank records are scored with
tools/score.py exactly like the official runner. Not limited by the one-simulation-per-workspace rule.

    python3 lab/harness.py <workflow_id> [--brief A|B] [--only PUB-01,PUB-04] [--reps 3] [--style talkative] [--workers 6] [--cases file.json]
"""
import argparse, concurrent.futures as cf, json, pathlib, sys, time

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "tools"), str(ROOT / "builder")]
import freya, llm
from score import http, score_ledger
from run_cases import persona_for, STYLES

SIM_MODEL = "google/gemini-3-flash"
JUDGE = """You judge one phone call between a bank's phone agent (AGENT) and a customer (USER). SYSTEM lines are tool calls the agent made and their results.
Tool names can be specific variants of the bank's tools (verify_date_of_birth and verify_phone_last4 are verify_identity calls). A failed call followed by a successful retry records one item. Lines starting with SYSTEM: call assess are internal checks, not bank calls.

Success criteria:
{criteria}

Read the whole call. Decide whether every criterion is met, reading each criterion for its intent. Reply with JSON only: {{"pass": true|false, "reason": "<one or two sentences; name the failed criterion and the message>"}}

CALL:
{transcript}"""


def chat(workflow_id, message, variables=None, call_id=None):
    """One turn. A 5xx after the turn was accepted is common when the turn runs a long chain of steps: never resend it."""
    body = {"workflowId": workflow_id, "message": message}
    if call_id:
        body["callId"] = call_id
    else:
        body["customerVariables"] = variables
    try:
        return freya.api("POST", "/api/v2/chat/message", body)
    except RuntimeError as e:
        if call_id is None:
            raise                       # never resend a first turn: it would open a second call for the same customer
        return {"callId": call_id, "response": "", "error": str(e)[:200]}

def opening_line(workflow_id, variables):
    """The fixed first line of the workflow (its initial node's TTS), with call variables filled in."""
    try:
        wf = freya.api("GET", f"/api/v2/workflow/{workflow_id}", workspaceId=freya.workspace_id())["workflow"]["workflow"]
        text = ((wf["nodes"][wf["initial_node"]].get("on_enter") or {}).get("text")) or ""
    except Exception:
        return ""
    for k, v in variables.items():
        text = text.replace("{{" + k + "}}", str(v))
    return text


def transcript_of(call, first_line=""):
    lines = []
    pending_close = []
    for m in call.get("messages", []):
        role, text = m.get("role"), m.get("message") or ""
        if role in ("assistant", "user"):
            if role == "user" and not lines and first_line:
                lines.append("AGENT: " + first_line)
            lines.append(("AGENT: " if role == "assistant" else "USER: ") + text)
            if role == "assistant" and pending_close:
                lines += pending_close
                pending_close = []
        elif role == "system":
            try:
                ev = json.loads(text)
            except ValueError:
                continue
            target = pending_close if (pending_close or ev.get("function") in ("close_call", "end_call") or "close_call" in json.dumps(ev.get("args") or "")) else lines
            if ev.get("event") == "function_call_start":
                body = ((ev.get("args") or {}).get("body")) if isinstance(ev.get("args"), dict) else None
                target.append(f"SYSTEM: call {ev.get('function')} {json.dumps(body if body is not None else ev.get('args'))[:300]}")
            elif ev.get("event") == "function_call_complete":
                res = ev.get("result")
                data = res.get("data") if isinstance(res, dict) else res
                target.append(f"SYSTEM: result {ev.get('function')} {json.dumps(data)[:300]}")
    return "\n".join(lines + pending_close)


def run_case(workflow_id, case, style=None, max_turns=40):
    sess = http("/v1/practice/sessions", {"case": case.get("session_case", case["id"])})["variables"]
    persona = persona_for(case, {"identity": case["identity"]}, style)
    system = persona["prompt"]
    history = []                       # from the customer's point of view: agent = user, customer = assistant
    first = opening_line(workflow_id, sess)
    if first:                           # a simulation starts with the agent's opening line; the customer answers it
        history.append({"role": "user", "content": first})
        customer_says = llm.call([{"role": "system", "content": system}, {"role": "user", "content": first}], model=SIM_MODEL, purpose=f"customer {case['id']}").strip() or "Hello?"
    else:
        customer_says = "Hello?"
    call_id, ended, turns = None, False, 0
    t0 = time.time()
    slowest = 0.0
    while turns < max_turns:
        turns += 1
        t1 = time.time()
        try:
            r = chat(workflow_id, customer_says, sess, call_id)
        except RuntimeError as e:
            ended = True
            break
        slowest = max(slowest, time.time() - t1)
        call_id = r.get("callId") or call_id
        agent = (r.get("response") or "").strip()
        history.append({"role": "assistant", "content": customer_says})
        history.append({"role": "user", "content": agent or "(silence)"})
        led = http("/v1/practice/ledger/" + sess["customer_id"])
        if led.get("calls") and led["calls"][-1]["tool"] == "close_call":
            ended = True
            break
        msgs = [{"role": "system", "content": system}] + [{"role": "user" if h["role"] == "user" else "assistant", "content": h["content"]} for h in history]
        customer_says = llm.call(msgs, model=SIM_MODEL, purpose=f"customer {case['id']}").strip() or "..."
    led = http("/v1/practice/ledger/" + sess["customer_id"])
    res = score_ledger(case, led)
    call = {}
    if call_id:
        try:
            freya.api("POST", "/api/v2/chat/end", {"callId": call_id})
        except RuntimeError:
            pass
        for _ in range(3):
            try:
                call = freya.get_call(call_id)
                break
            except RuntimeError:
                time.sleep(2)
    tr = transcript_of(call, first) if call else "\n".join(("USER: " if h["role"] == "assistant" else "AGENT: ") + h["content"] for h in history)
    verdict = {"pass": False, "reason": "no verdict"}
    try:
        verdict = llm.parse_json(llm.call([{"role": "user", "content": JUDGE.format(criteria=persona["successCriteria"], transcript=tr)}], model=SIM_MODEL, purpose=f"judge {case['id']}", json_mode=True))
    except Exception as e:
        verdict = {"pass": False, "reason": f"judge error {e}"}
    if not verdict.get("pass"):
        res["failed"].append("conversation: " + str(verdict.get("reason"))[:400])
    res["pass"] = not res["failed"]
    return {"id": case["id"], "level": case["level"], "family": case["family"], "style": style, "pass": res["pass"], "failed": res["failed"],
            "tools": [c["tool"] for c in led.get("calls", [])], "call_id": call_id, "customer_id": sess["customer_id"], "turns": turns,
            "seconds": round(time.time() - t0), "slowest_turn_s": round(slowest, 1), "transcript": tr}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("workflow_id"); ap.add_argument("--brief"); ap.add_argument("--only"); ap.add_argument("--reps", type=int, default=1)
    ap.add_argument("--style", help="one style, 'all' for every style, or 'mix' to rotate styles over reps")
    ap.add_argument("--workers", type=int, default=6); ap.add_argument("--cases", default=str(ROOT / "public-test-set.json")); ap.add_argument("--out")
    a = ap.parse_args()
    cases = [c for c in json.load(open(a.cases)) if (not a.brief or c["brief"] in a.brief.split(",")) and (not a.only or c["id"] in a.only.split(","))]
    styles = sorted(STYLES)
    jobs = []
    for rep in range(a.reps):
        for c in cases:
            st = a.style
            if st == "mix":
                st = ([None] + styles)[(rep + cases.index(c)) % (len(styles) + 1)]
            if st == "all":
                jobs += [(c, s) for s in [None] + styles]
            else:
                jobs.append((c, st))
    t0 = time.time()
    rows = []
    with cf.ThreadPoolExecutor(a.workers) as ex:
        futs = {ex.submit(run_case, a.workflow_id, c, s): (c, s) for c, s in jobs}
        for f in cf.as_completed(futs):
            c, s = futs[f]
            try:
                r = f.result()
            except Exception as e:
                r = {"id": c["id"], "level": c["level"], "family": c["family"], "style": s, "pass": False, "failed": [f"harness error: {e}"], "tools": []}
            rows.append(r)
            print(("PASS" if r["pass"] else "FAIL"), r["id"], f"{r['level']:<6}", f"{r['family']:<14}", f"[{s or 'plain'}]", "|",
                  " > ".join(t.replace("verify_identity", "verify").replace("create_promise", "promise") for t in r["tools"]) or "(no tool calls)", flush=True)
            for x in r["failed"]:
                print("       -", x[:300], flush=True)
    by = {}
    for r in rows:
        by.setdefault(r["id"], []).append(r["pass"])
    n = sum(all(v) for v in by.values())
    print(f"\n{n} / {len(by)} cases passed every run ({sum(r['pass'] for r in rows)} / {len(rows)} runs). {time.time() - t0:.0f} s. LLM spend so far ${llm.spent():.2f}")
    out = a.out or str(ROOT / "results" / f"harness-{time.strftime('%H%M%S')}.json")
    pathlib.Path(out).parent.mkdir(exist_ok=True)
    json.dump({"workflow_id": a.workflow_id, "rows": sorted(rows, key=lambda r: r["id"])}, open(out, "w"), indent=1)
    print("saved", out)


if __name__ == "__main__":
    main()
