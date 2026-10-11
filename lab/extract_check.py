"""Extract a spec for a brief, diff it against an expected spec, compile it and self-test its policy. No Freya writes.

    python3 lab/extract_check.py <brief.md> <openapi.json> <expected.json> <out_spec.json>
"""
import json, pathlib, subprocess, sys
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "builder"), str(ROOT)]
from extract import extract
from compile import compile_workflow
from build import policy_selftest

brief, oa_path, exp, out = sys.argv[1:5]
oa = json.load(open(oa_path))
spec = extract(pathlib.Path(brief).read_text(), oa, trace=lambda m: print(m[:300], flush=True))
pathlib.Path(out).write_text(json.dumps(spec, indent=1))
print(subprocess.run([sys.executable, str(ROOT / "lab/diff_spec.py"), exp, out], capture_output=True, text=True).stdout)
wf = compile_workflow(spec, oa)
print("compiled", len(wf["nodes"]), "nodes")
print("self-test problems:", policy_selftest(spec, lambda m: print(m[:200])))
