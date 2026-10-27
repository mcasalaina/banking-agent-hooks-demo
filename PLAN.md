# Banking Agent Hooks Demo

## Goal

Build a presentation-first banking payments agent that makes Microsoft Agent Framework (MAF) Agent Hooks visible and understandable in a recorded video and on a stage. The demo should show that a hook decision controls execution, rather than merely logging what the model said it would do.

The scenario complements the retail and commercial bank in the Gartner AI application development platform demo scenario. Use synthetic customers, beneficiaries, accounts, and payment records only.

## Audience takeaway

> The model proposes the action. The bank's policy layer controls execution.

Audience members should be able to see what the agent proposed, which hook evaluated it, the verdict and reason, and whether the payment tool and ledger were actually affected.

## Demo experience

Use a full-screen 16:9 layout with three persistent areas:

- **Customer request:** concise conversation and a prominent transfer proposal card.
- **Policy checkpoint:** a central, visually dominant MAF Hook gate showing `ALLOWED`, `AWAITING APPROVAL`, or `BLOCKED`, plus a human-readable reason and the technical interception point.
- **Bank outcome:** a simulated payment ledger, transaction receipt when applicable, and an unmistakable `NO MONEY MOVED` state when execution did not occur.

Show a simple execution path along the bottom:

`Request -> Model proposes transfer -> Hook checks policy -> Payment tool -> Receipt`

Animate/highlight the path from actual runtime and payment-service events. A denial must stop the path before the payment tool. Keep the final hook decision visible until the presenter starts the next scenario; do not fabricate enforcement delays.

Keep detailed, payload-minimized hook records in the state API, without a developer drawer on the presentation screen. The main stage view should favor large type, high contrast, short explanations, and text/icons in addition to color.

## Presentation scenarios

Provide a compact scenario dropdown, an explicit Run button, and a reliable reset for each case:

1. **Routine payment:** transfer `$200` to a saved beneficiary. The hook allows it, the payment tool executes, and the ledger and receipt show the result.
2. **Approval required:** transfer `$15,000` to a new beneficiary. The hook escalates to a human approver. The ledger remains unchanged while pending; approve to continue and show the completed transaction.
3. **Frozen beneficiary:** transfer to a beneficiary marked frozen in the authoritative synthetic bank records. The hook denies the tool call; show `PAYMENT TOOL NOT EXECUTED` and `NO MONEY MOVED`.
4. **Prompt-injection pressure:** supply an untrusted operations update claiming the frozen beneficiary has been verified. The policy still denies based on authenticated identity and bank records, not the conversation's claims. Keep the model provider's content-safety policies enabled.

Optional stretch scenario: a `post_tool_call` transform masks a synthetic account number before the result reaches the model. Include only if it can be clearly distinguished from the primary authorization story.

## Functional requirements

- Use MAF Agent Framework Agent Hooks with framework-executed function tools for payment actions so `pre_tool_call` can prevent execution.
- Implement policy checks against trusted, synthetic bank state, not prompt-only rules. Keep ordinary authorization and validation in the payment service as well; hooks complement, not replace, backend security.
- Capture actual hook interception records and actual payment-service outcomes as structured events. Never infer success or denial from the assistant's prose.
- Display interception point, policy name/version, verdict, concise reason, and timestamp. Keep correlation IDs in the structured event records, not the main stage view. Do not expose real or unnecessary account data in the event feed.
- Support approval as a real paused decision with explicit approve/reject outcomes and no ledger mutation before approval.
- Handle hook, model, and service failures explicitly. Never fall back to a success-shaped canned response.
- Make scenario reset deterministic and keep all demo data synthetic.

## Reliability and video/stage requirements

- Use preset prompts selected with a compact dropdown and Run button to avoid typing errors during a live presentation.
- Provide a visible reset and clear current-scenario indicator.
- Keep the main state legible from a distance and the hook outcome on screen long enough for narration.
- Run every scenario through the real Foundry model, attaching Agent Hooks when enabled. Do not provide a scripted execution mode or fallback.
- Provide a Hooks on/off toggle for a live comparison. Changing it resets the screen and ledger to their pre-run state without starting a payment, showing the Agent Hooks panel only when enabled. Off omits the hook middleware entirely, while retaining model calls and payment-service validation. Display bypassed hooks honestly and never fabricate hook records or approvals.
- Ensure a failure is visibly reported and does not appear as an allowed or completed payment.

## Technical notes and constraints

- MAF Agent Hooks are documented as experimental and currently Python-only. Confirm the SDK versions and APIs during implementation; isolate hook integration so changes to the experimental API are manageable.
- Use the Agent Hooks `record_sink` (or the current supported equivalent) to feed the UI's structured event stream.
- Keep the policy decision, payment-tool result, and ledger mutation separately observable so the demo can prove both the hook verdict and its consequence.
- Avoid external payment rails, real accounts, and real customer information.

## Delivery phases

1. **Validate framework path:** confirm the current MAF/Agent Hooks APIs, tool interception behavior, approval flow, and event records with a minimal local proof of concept.
2. **Build the deterministic payment demo:** synthetic bank state, payment tool, policy checks, approval decision, ledger, and resettable scenarios.
3. **Build the presentation UI:** 16:9 three-area layout, execution path, prominent verdict cards, live ledger, and compact scenario controls.
4. **Integrate and verify:** connect UI to real hook and payment events; verify allowed, escalated, denied, and failure cases end to end.
5. **Presentation hardening:** test at stage/video dimensions, refine timing and legibility, rehearse full reset and connection-recovery workflows, and document startup/demo steps.

## Acceptance criteria

- The routine scenario visibly shows the hook allow, actual tool execution, and ledger update.
- The approval scenario visibly pauses before payment; rejecting it causes no ledger update, and approving it produces one.
- The frozen-beneficiary scenario and prompt-injection variant visibly show a hook denial, no tool execution, and no ledger change.
- The UI's displayed decision and outcome come from runtime events, not generated assistant text.
- Hook/model/service failures are explicit and cannot be mistaken for payment success.
- The main view is readable in a 16:9 video/stage presentation, and decisions remain visible until the presenter advances.
- A fresh run can be reset to a known synthetic state and repeat all primary scenarios.
- With hooks off, high-value transfers execute without the hook's approval pause, while frozen recipients are declined by the payment service after tool invocation. No hook interception records are emitted. Re-enabling hooks restores the approval and pre-tool denial behavior.
