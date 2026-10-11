# Final runbook (final case opens 17:00 UTC, submissions close 20:00 UTC)

The final is one case (Turkish). Input: a zip with a folder of the bank's documents (Markdown, Word, PDF, Excel):
`BRIEF.md`, `README.md`, a service contract, test customers and six example conversations.

1. Get the latest builder and the keys: `git pull && source env.sh`.
2. Unzip the case into `cases/` (for example `cases/<CaseFolder>/`).
3. Write the mock of the bank's services in `mock/` (Cloudflare Workers) from the service contract and the test
   customers: `mock/src/routes.js` (endpoints), `mock/src/customers.js` (data). Deploy with `cd mock && wrangler deploy`.
   URL: `https://wired-bank-mock.barisbayburtlu33.workers.dev`. Keep it running until the results are out.
   Debug endpoints: `GET /_health`, `GET /_log`, `GET /_records`, `POST /_reset`.
4. Run the builder on the folder and keep everything it prints:

   ```bash
   python3 builder/build.py cases/<CaseFolder> https://wired-bank-mock.barisbayburtlu33.workers.dev 2>&1 | tee traces/final.log
   ```

   It exports the phone agent to `submission/<CaseFolder>.workflow.json`. Copy it to `submission/final.workflow.json`.
   Do not edit the phone agent after the run. If a run fails, fix the builder generically (never write anything
   from the case into it), commit, and run again.
5. Test the agent against the mock: `python3 lab/final_harness.py <workflow_id> <cases.json> <mock_url>`.
6. Commit and push traces and the workflow, make the repo public:

   ```bash
   git add traces submission mock && git commit -m "Final run" && git push && git rev-parse --short HEAD
   gh repo edit byigitt/freya-build-the-builder --visibility public --accept-visibility-change-consequences
   ```

7. Before 20:00 UTC send `submission.json` to the address in the kit e-mail:

   ```json
   {
     "team": "wired",
     "members": [{"name": "Barış Bayburtlu", "email": "barisbayburtlu33@gmail.com"}],
     "repo": "https://github.com/byigitt/freya-build-the-builder",
     "commit": "<short hash from step 6>",
     "run_command": "python3 builder/build.py {case_folder} {mock_url}",
     "workflow": "submission/final.workflow.json",
     "trace": "traces/final.log",
     "mock_url": "https://wired-bank-mock.barisbayburtlu33.workers.dev"
   }
   ```
