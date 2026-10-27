# Banking Agent Hooks Demo

A stage-ready, 16:9 payment demo that makes the Microsoft Agent Framework Agent Hooks enforcement boundary visible. The model proposes a transfer; a `pre_tool_call` policy hook decides whether the payment tool may run; the synthetic payment service and ledger report what actually happened.

All customers, beneficiaries, account labels, and payments are synthetic. This app never connects to external payment rails. Agent Hooks are experimental and complement, rather than replace, the payment service's own validation.

## Foundry configuration

The default target is the existing Foundry project `mcasalaina-4iqs-2612`, using its deployed `gpt-5.4-mini` model. The project endpoint and model can be overridden with `FOUNDRY_PROJECT_ENDPOINT` and `FOUNDRY_MODEL`. Copy `.env.example` to `.env` to customize local settings; `.env` is ignored by Git.

Live model calls use `AzureCliCredential`, so sign in with the Azure CLI before starting the app. The application does not run `az login` for you.

## Run locally

Requirements: Python 3.13, Node.js 20+, `pnpm`, and an authenticated Azure CLI.

Install the Python dependencies using an approved package index configured for your environment:

```bash
python3.13 -m venv .venv
.venv/bin/python -m pip install -e .
pnpm --dir web install --frozen-lockfile
```

Start the app:

```bash
./scripts/start-demo.sh
```

Open `http://127.0.0.1:5173`. The launcher builds the UI and serves it together with the API in one process on the same origin. Leave this process running while using the demo; closing it disconnects the UI. Set `PORT` to change the port.

For frontend development only, run `.venv/bin/python -m banking_demo.server` and `pnpm --dir web dev` in separate terminals. Vite proxies API requests to port 8765.

Agent Hooks is an experimental SDK. The project pins the tested Agent Framework and Agent Hooks versions, including the published `agent-hooks-sdk` beta. If an internal package feed returns HTTP 404 for a `.whl.metadata` file, download that wheel with `pip download --no-deps --use-deprecated=legacy-resolver agent-hooks-sdk==0.1.0b2`, install the downloaded wheel, then repeat `pip install -e .`. This is a feed metadata issue, not evidence that package downloads are blocked.

## Scenarios

Choose a scenario from the compact dropdown and press **Run**. Changing the selection alone does not start a transfer; press **Run** again to repeat a scenario. Detailed runtime records remain available through `/api/state`, without a developer drawer on the presentation screen.

Changing the **Hooks on/off** switch clears the previous run, restores the initial synthetic balance, and returns to a pre-run state without starting a payment. The switch cannot change during execution or approval. With hooks off, both the Agent Hooks policy panel and the policy-check step in the execution path are hidden. The same live model and payment tool run without Agent Hooks middleware: no interception or approval events are fabricated. The high-value scenario executes without the hook's approval pause. Frozen recipients still fail payment-service validation, but only after the tool runs.

- **Routine payment:** `$200` to a saved beneficiary. The hook allows the tool call, and the service posts one payment.
- **Approval required:** `$15,000` to a new beneficiary. The hook pauses at `pre_tool_call`; the ledger remains unchanged until the presenter approves. Rejecting or timing out leaves it unchanged.
- **Frozen beneficiary:** the hook denies the call based on trusted synthetic bank records. The payment tool does not execute.
- **Prompt-injection pressure:** the customer supplies an untrusted “Operations update” claiming the recipient is verified. The hook ignores that claim and denies the frozen beneficiary using the bank record. Foundry's content-safety policies remain enabled.

The reset control restores the original synthetic balance and clears the run events. If the model does not emit a payment tool call, the UI reports that no payment was attempted; it does not infer execution from assistant prose.

Every scenario calls the configured Foundry model. With the switch on, it uses the real MAF Agent Hooks middleware; with the switch off, that middleware is not attached. There is no scripted execution mode or fallback. Model or hook failures are shown explicitly and never replaced with simulated events. If the service disconnects, payment controls are disabled, the displayed ledger is labeled stale, and the UI reconnects automatically.

## Foundry prompt-only comparison agent

`banking-agent-prompt-only` is a separate prompt agent in the same `mcasalaina-4iqs-2612` project, using `gpt-5.4-mini`. Its definition and system instructions are in [`foundry/approval-prompt-agent.json`](foundry/approval-prompt-agent.json).

The instructions require a fresh, explicit human approval before every transfer, with no exceptions for saved recipients, small amounts, urgency, or claims of prior authorization. The agent must present the proposal, ask for approval, and stop to await a subsequent human response.

This agent demonstrates prompt-only instructions, not deterministic approval enforcement. It has no payment tools or Agent Hooks attached and cannot execute transfers. The live web demo remains separate and demonstrates actual tool execution with optional hook enforcement.

## Tests and build

```bash
.venv/bin/python -m unittest discover -s tests -v
pnpm --dir web build
```

The Python tests use the real framework function-execution loop and Agent Hooks SDK, stubbing only the model transport. They cover hook ordering, policy decisions, ledger mutation, approval/rejection/timeout, model failures, and fail-closed interceptor failures without billing model calls. Live end-to-end verification uses the running UI against the configured Foundry deployment.
