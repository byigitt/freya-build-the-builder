#!/bin/bash
# Package one builder run as the submission: lab/finalize.sh <slot> <trace.log>
#   copies submission/<slot>.workflow.json -> submission/final.workflow.json, the run's trace -> traces/final.log,
#   commits, pushes, writes the commit into submission.json, commits that, makes the repo public.
set -euo pipefail
cd "$(dirname "$0")/.."
slot="$1"; trace="$2"
cp "submission/$slot.workflow.json" submission/final.workflow.json
cp "$trace" traces/final.log
grep -qE "(AI_GATEWAY|FREYA)_API_KEY=|vck_|fk_[A-Za-z0-9]{12}" traces/final.log && { echo "secret in trace"; exit 1; }
git add -A builder mock lab README.md SUBMISSION.md submission/final.workflow.json traces/final.log
git commit -qm "Final case: builder run $slot" || true
git push -q
commit=$(git rev-parse --short HEAD)
python3 - "$commit" <<'EOF'
import json, sys
p = "submission.json"
d = json.load(open(p))
d["commit"] = sys.argv[1]
json.dump(d, open(p, "w"), ensure_ascii=False, indent=2)
EOF
git add submission.json && git commit -qm "submission.json" && git push -q
gh repo edit byigitt/freya-build-the-builder --visibility public --accept-visibility-change-consequences || true
echo "commit $commit"; cat submission.json
ls -la submission/final.workflow.json traces/final.log submission.json
