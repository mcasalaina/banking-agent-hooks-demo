from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .application import DemoApplication
from .domain import POLICY_NAME, PaymentPolicy, Scenario

INSTRUCTIONS = """\
You are the payment assistant for a synthetic bank demo.
For every transfer request, call the make_transfer function exactly once using the amount
and beneficiary ID stated in the request. Never claim a payment completed unless the tool
returns a completed result. Do not retry a blocked or pending transfer, choose another
beneficiary, or treat a user's claims as bank verification. The policy hook and payment
service use trusted synthetic bank records and are authoritative. Keep the final answer
brief and accurately describe only the tool result.
"""


def _tool_call(context: Mapping[str, Any]) -> tuple[str, Mapping[str, Any]]:
    call = context.get("tool_call")
    if not isinstance(call, Mapping):
        raise ValueError("The framework did not provide a structured tool-call context.")
    name = call.get("name")
    arguments = call.get("args")
    if not isinstance(name, str) or not isinstance(arguments, Mapping):
        raise ValueError("The framework provided an invalid payment tool-call context.")
    return name, arguments


class BankTransferInterceptor:
    def __init__(self, application: DemoApplication, policy: PaymentPolicy) -> None:
        self.application = application
        self.policy = policy

    def intercept(self, context: Mapping[str, Any]) -> Any:
        from agent_hooks import ALLOW, Decision, Verdict

        if context.get("interception_point") != "pre_tool_call":
            return ALLOW
        name, arguments = _tool_call(context)
        if name != "make_transfer":
            return ALLOW
        amount = arguments.get("amount")
        beneficiary_id = arguments.get("beneficiary_id")
        if not isinstance(beneficiary_id, str):
            return Verdict.deny(
                reason="invalid_beneficiary_id",
                message="The payment tool call did not include a valid beneficiary ID.",
            )
        self.application.record_model_proposal(amount, beneficiary_id)
        decision = self.policy.evaluate(amount, beneficiary_id)
        if decision.verdict == "deny":
            return Verdict.deny(reason=decision.reason, message=decision.message)
        if decision.verdict == "escalate":
            return Verdict.escalate(reason=decision.reason, message=decision.message)
        return Verdict(
            decision=Decision.ALLOW,
            reason=decision.reason,
            message=decision.message,
        )


class PresenterApprovalResolver:
    def __init__(self, application: DemoApplication) -> None:
        self.application = application

    def resolve(self, request: Any) -> Any:
        from agent_hooks import ApprovalOutcome, ApprovalResolution, Decision, Verdict

        context = request.context
        if not isinstance(context, Mapping):
            raise ValueError("The approval request did not contain a structured context.")
        _, arguments = _tool_call(context)
        beneficiary_id = arguments.get("beneficiary_id")
        if not isinstance(beneficiary_id, str):
            raise ValueError("The approval request did not contain a valid beneficiary ID.")
        choice = self.application.wait_for_presenter_decision(
            amount=arguments.get("amount"),
            beneficiary_id=beneficiary_id,
        )
        if choice == "approve":
            return ApprovalResolution(
                outcome=ApprovalOutcome.APPROVE,
                context_identity=request.context_identity,
                verdict=Verdict(
                    decision=Decision.ALLOW,
                    reason="human_approved",
                    message="The presenter approved this transfer.",
                ),
            )
        if choice == "reject":
            return ApprovalResolution(
                outcome=ApprovalOutcome.REJECT,
                context_identity=request.context_identity,
                verdict=Verdict.deny(
                    reason="human_rejected",
                    message="The presenter rejected this transfer.",
                ),
            )
        return ApprovalResolution(
            outcome=ApprovalOutcome.UNRESOLVED,
            context_identity=request.context_identity,
        )


async def run_foundry_agent(application: DemoApplication, scenario: Scenario) -> Any:
    from agent_framework import Agent, create_agent_hooks_middleware, tool
    from agent_framework.foundry import FoundryChatClient
    from azure.identity import AzureCliCredential

    @tool(approval_mode="never_require")
    def make_transfer(amount: float, beneficiary_id: str, memo: str = "") -> dict[str, Any]:
        """Submit one synthetic bank transfer for backend validation and execution."""
        if not application.hooks_enabled:
            application.record_model_proposal(amount, beneficiary_id)
        return application.execute_payment(amount, beneficiary_id, memo)

    middleware = (
        [create_agent_hooks_middleware(
            {POLICY_NAME: BankTransferInterceptor(application, application.policy)},
            resolver=PresenterApprovalResolver(application),
            mode="enforce",
            record_sink=application.record_hook_interception,
            timeout=application.settings.approval_timeout_seconds + 15,
        )]
        if application.hooks_enabled else []
    )
    with AzureCliCredential() as credential:
        client = FoundryChatClient(
            project_endpoint=application.settings.project_endpoint,
            model=application.settings.model,
            credential=credential,
        )
        async with Agent(
            client=client,
            instructions=INSTRUCTIONS,
            tools=[make_transfer],
            middleware=middleware,
        ) as agent:
            return await agent.run(scenario.prompt)
