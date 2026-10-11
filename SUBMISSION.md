# Sunday runbook (hidden briefs open 17:00 UTC, submissions close 20:00 UTC)

1. Get the latest builder and the keys.

   ```bash
   git pull && source env.sh
   ```

2. Save each hidden brief and its tool API file next to the public ones:

   ```
   briefs/hidden-1.md   briefs/hidden-1.openapi.json
   briefs/hidden-2.md   briefs/hidden-2.openapi.json
   ```

3. Run the builder once per brief and keep everything it prints (about 3 minutes each):

   ```bash
   python3 builder/build.py briefs/hidden-1.md briefs/hidden-1.openapi.json 2>&1 | tee traces/hidden-1.log
   python3 builder/build.py briefs/hidden-2.md briefs/hidden-2.openapi.json 2>&1 | tee traces/hidden-2.log
   ```

   Each run exports its phone agent to `submission/<brief>.workflow.json` and writes a detailed trace to
   `traces/<brief>-<time>.log`. Check the trace: `self-test problems: 0`, `bank-call audit: every bank call sends ...`,
   and the chat smoke test line. Do not edit the phone agent after the run. If a run fails, fix the builder (never by
   writing anything from a hidden brief into it), commit the fix, and run again.

4. Commit and push the traces and the exported workflows:

   ```bash
   git add traces submission && git commit -m "Hidden brief runs" && git push && git rev-parse --short HEAD
   ```

5. Send the form before 20:00 UTC:

   ```json
   {
     "team": "wired",
     "repo": "https://github.com/byigitt/freya-build-the-builder",
     "commit": "<short hash from step 4>",
     "run_command": "python3 builder/build.py {brief_path} {tool_api_path}",
     "workflows": {"hidden-1": "submission/hidden-1.workflow.json", "hidden-2": "submission/hidden-2.workflow.json"},
     "traces": {"hidden-1": "traces/hidden-1.log", "hidden-2": "traces/hidden-2.log"}
   }
   ```

Before sending the form, make the repository public: `gh repo edit byigitt/freya-build-the-builder --visibility public --accept-visibility-change-consequences`.
