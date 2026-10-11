"""tools/run_cases.py with a watchdog: a simulation whose runs have all ended but whose status stays 'running' is marked
completed instead of blocking the workspace forever. Same arguments as tools/run_cases.py."""
import pathlib, sys, time
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "tools")]
import freya
import run_cases

_orig_api = freya.api


def unstick_running():
    try:
        r = freya.api("GET", "/api/v2/simulations", workspaceId=freya.workspace_id(), limit=5)
        items = r.get("simulations") or r.get("items") or r
        for s in items:
            if s.get("status") != "running":
                continue
            its = freya.api("GET", f"/api/v2/simulations/{s['id']}/iterations")
            its = its.get("iterations") or its
            if not its:
                continue
            runs = freya.get_iteration(s["id"], its[0]["id"])["runs"]
            if runs and all(x.get("endedAt") for x in runs):
                age = time.time() - max(time.mktime(time.strptime(x["endedAt"][:19], "%Y-%m-%dT%H:%M:%S")) for x in runs) + time.timezone
                if age > 120:
                    freya.api("PUT", f"/api/v2/simulations/{s['id']}", {"status": "completed"})
                    print("watchdog: marked stuck simulation", s["id"], "completed", flush=True)
    except Exception as e:
        print("watchdog error", str(e)[:200], flush=True)


def run_simulation(agent_id, name, variables_by_persona, max_seconds=420, concurrency=10):
    unstick_running()
    while True:
        try:
            sim = freya.api("POST", "/api/v2/simulations", {
                "agentId": agent_id, "name": name, "mode": "chat", "selectedPersonaIds": list(variables_by_persona),
                "customerVariablesMap": variables_by_persona, "maxConcurrentCalls": concurrency, "runsPerPersona": 1, "maxCallDurationSeconds": max_seconds,
                "assistantLlmOverride": freya.AGENT_LLM, "routingLlmOverride": freya.AGENT_LLM, "extractionLlmOverride": freya.AGENT_LLM,
                "personaLlmOverride": freya.SIM_LLM, "analysisLlmOverride": freya.SIM_LLM})
            break
        except RuntimeError as e:
            if "concurrent simulations" not in str(e):
                raise
            print("another simulation is running in this workspace, waiting 30 s", flush=True)
            time.sleep(30)
            unstick_running()
    sim_id = (sim.get("simulation") or sim)["id"]
    t0 = time.time()
    while True:
        time.sleep(10)
        s = freya.api("GET", f"/api/v2/simulations/{sim_id}")
        s = s.get("simulation") or s
        if s.get("status") in ("completed", "failed", "paused"):
            break
        if time.time() - t0 > 240:
            its = freya.api("GET", f"/api/v2/simulations/{sim_id}/iterations")
            its = its.get("iterations") or its
            runs = freya.get_iteration(sim_id, its[0]["id"])["runs"] if its else []
            if runs and all(x.get("endedAt") for x in runs) and time.time() - t0 > 300:
                freya.api("PUT", f"/api/v2/simulations/{sim_id}", {"status": "completed"})
                print("watchdog: all runs ended, closing simulation", flush=True)
                break
    its = freya.api("GET", f"/api/v2/simulations/{sim_id}/iterations")
    its = its.get("iterations") or its.get("items") or its
    return sim_id, its[0]["id"], s.get("status")


freya.run_simulation = run_simulation
run_cases.freya.run_simulation = run_simulation
if __name__ == "__main__":
    run_cases.main()
