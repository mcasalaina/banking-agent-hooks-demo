from __future__ import annotations

import asyncio
import importlib.util
import threading
import time
import uuid
from datetime import UTC, datetime
from typing import Any

from .config import Settings
from .domain import (
    POLICY_NAME,
    POLICY_VERSION,
    SCENARIOS,
    PaymentPolicy,
    Scenario,
    SyntheticBank,
    amount_to_cents,
)


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class DemoBusyError(Exception):
    pass


class DemoApplication:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._lock = threading.RLock()
        self.bank = SyntheticBank()
        self.policy = PaymentPolicy(self.bank)
        self.hooks_enabled = True
        self._events: list[dict[str, Any]] = []
        self._run_status = "idle"
        self._scenario: Scenario | None = None
        self._correlation_id: str | None = None
        self._assistant_response: str | None = None
        self._error: dict[str, str] | None = None
        self._approval: dict[str, Any] | None = None
        self._approval_event: threading.Event | None = None
        self._approval_choice: str | None = None
        self._worker: threading.Thread | None = None

    def _emit(self, event_type: str, **fields: Any) -> None:
        with self._lock:
            self._events.append(
                {
                    "event_id": uuid.uuid4().hex[:12],
                    "type": event_type,
                    "timestamp": utc_now(),
                    "correlation_id": self._correlation_id,
                    "origin": "live",
                    **fields,
                }
            )

    def start_scenario(self, scenario_id: str, *, hooks_enabled: bool = True) -> dict[str, Any]:
        if not isinstance(hooks_enabled, bool):
            raise ValueError("hooks_enabled must be a boolean.")
        scenario = SCENARIOS.get(scenario_id)
        if scenario is None:
            raise ValueError("Unknown scenario.")
        with self._lock:
            if self._run_status in {"running", "awaiting_approval"}:
                raise DemoBusyError("A scenario is already in progress.")
            self.hooks_enabled = hooks_enabled
            self.bank.reset()
            self._events = []
            self._scenario = scenario
            self._correlation_id = uuid.uuid4().hex
            self._assistant_response = None
            self._error = None
            self._approval = None
            self._approval_event = None
            self._approval_choice = None
            self._run_status = "running"
            self._emit(
                "request_received",
                scenario_id=scenario.scenario_id,
                scenario_title=scenario.title,
                hooks_enabled=hooks_enabled,
            )
            self._worker = threading.Thread(
                target=self._run_live,
                args=(scenario,),
                name=f"bank-demo-{scenario.scenario_id}",
                daemon=True,
            )
            self._worker.start()
            return self.snapshot()

    def reset(self, *, hooks_enabled: bool | None = None) -> dict[str, Any]:
        if hooks_enabled is not None and not isinstance(hooks_enabled, bool):
            raise ValueError("hooks_enabled must be a boolean.")
        with self._lock:
            if self._run_status in {"running", "awaiting_approval"}:
                raise DemoBusyError("Wait for the active scenario to finish before resetting.")
            if hooks_enabled is not None:
                self.hooks_enabled = hooks_enabled
            self.bank.reset()
            self._events = []
            self._run_status = "idle"
            self._scenario = None
            self._correlation_id = None
            self._assistant_response = None
            self._error = None
            self._approval = None
            self._approval_event = None
            self._approval_choice = None
            return self.snapshot()

    def resolve_approval(self, decision: str) -> dict[str, Any]:
        if decision not in {"approve", "reject"}:
            raise ValueError("Decision must be 'approve' or 'reject'.")
        with self._lock:
            if (
                self._run_status != "awaiting_approval"
                or self._approval_event is None
                or self._approval is None
                or self._approval.get("status") != "pending"
            ):
                raise DemoBusyError("There is no pending approval decision.")
            self._approval_choice = decision
            self._approval["status"] = decision
            self._approval["resolved_at"] = utc_now()
            self._run_status = "running"
            self._emit(
                "human_approval",
                decision=decision,
                policy=POLICY_NAME,
                policy_version=POLICY_VERSION,
            )
            self._approval_event.set()
            return self.snapshot()

    def wait_for_presenter_decision(
        self,
        *,
        amount: Any,
        beneficiary_id: str,
    ) -> str:
        beneficiary = self.bank.beneficiary(beneficiary_id)
        cents = amount_to_cents(amount)
        event = threading.Event()
        details = {
            "status": "pending",
            "amount_cents": cents,
            "beneficiary_id": beneficiary_id,
            "beneficiary_name": beneficiary.name if beneficiary else "Unknown beneficiary",
            "account_suffix": beneficiary.account_suffix if beneficiary else None,
            "policy": POLICY_NAME,
            "policy_version": POLICY_VERSION,
            "interception_point": "pre_tool_call",
        }
        with self._lock:
            self._approval = details
            self._approval_event = event
            self._approval_choice = None
            self._run_status = "awaiting_approval"
            self._emit(
                "approval_requested",
                amount_cents=cents,
                beneficiary_id=beneficiary_id,
                beneficiary_name=details["beneficiary_name"],
                account_suffix=details["account_suffix"],
                policy=POLICY_NAME,
                policy_version=POLICY_VERSION,
                interception_point="pre_tool_call",
            )

        approved_in_time = event.wait(self.settings.approval_timeout_seconds)
        with self._lock:
            if not approved_in_time or self._approval_choice is None:
                if self._approval is not None:
                    self._approval["status"] = "timed_out"
                    self._approval["resolved_at"] = utc_now()
                self._run_status = "running"
                self._emit(
                    "approval_timeout",
                    policy=POLICY_NAME,
                    policy_version=POLICY_VERSION,
                    interception_point="pre_tool_call",
                )
                return "unresolved"
            return self._approval_choice

    def record_hook_interception(self, record: Any) -> None:
        verdict = record.verdict
        decision = verdict.decision.value
        policy_summary = next(
            (
                item for item in record.verdicts
                if item.name == POLICY_NAME and item.decision.value == decision
            ),
            None,
        )
        interceptor_name = POLICY_NAME
        if record.verdicts:
            decided_by = record.decided_by
            if decided_by is not None:
                matching = next(
                    (item for item in record.verdicts if item.index == decided_by),
                    None,
                )
                if matching is not None and matching.name:
                    interceptor_name = matching.name
        self._emit(
            "hook_interception",
            interception_point=record.interception_point.value,
            policy=interceptor_name,
            policy_version=POLICY_VERSION,
            verdict=decision,
            message=verdict.message,
            reason=verdict.reason or (policy_summary.reason if policy_summary else None),
            resolved_by=record.resolved_by,
            timestamp=record.timestamp or utc_now(),
            hook_sequence=record.sequence,
            hook_session_id=record.session_id,
            correlation_id=self._correlation_id,
        )

    def record_model_proposal(self, amount: Any, beneficiary_id: str) -> None:
        beneficiary = self.bank.beneficiary(beneficiary_id)
        cents = amount_to_cents(amount)
        self._emit(
            "model_proposed_transfer",
            amount_cents=cents,
            beneficiary_id=beneficiary_id,
            beneficiary_name=beneficiary.name if beneficiary else "Unknown beneficiary",
            account_suffix=beneficiary.account_suffix if beneficiary else None,
            source="framework_tool_call",
        )

    def execute_payment(self, amount: Any, beneficiary_id: str, memo: str = "") -> dict[str, Any]:
        beneficiary = self.bank.beneficiary(beneficiary_id)
        cents = amount_to_cents(amount)
        self._emit(
            "payment_tool_started",
            amount_cents=cents,
            beneficiary_id=beneficiary_id,
            beneficiary_name=beneficiary.name if beneficiary else "Unknown beneficiary",
            service="synthetic-payment-service",
        )
        outcome = self.bank.execute_transfer(
            amount,
            beneficiary_id,
            memo,
            self._correlation_id or "unbound",
        )
        self._emit(
            "payment_service_outcome",
            status=outcome["status"],
            reason=outcome.get("reason"),
            transaction_id=outcome.get("transaction_id"),
            amount_cents=outcome.get("amount_cents", cents),
            beneficiary_id=outcome.get("beneficiary_id", beneficiary_id),
            beneficiary_name=outcome.get(
                "beneficiary_name",
                beneficiary.name if beneficiary else "Unknown beneficiary",
            ),
            balance_cents=outcome.get("balance_cents"),
            service="synthetic-payment-service",
        )
        if outcome["status"] == "completed":
            self._emit(
                "receipt_created",
                transaction_id=outcome["transaction_id"],
                amount_cents=outcome["amount_cents"],
                beneficiary_id=outcome["beneficiary_id"],
                beneficiary_name=outcome["beneficiary_name"],
                balance_cents=outcome["balance_cents"],
            )
        return outcome

    def health(self) -> dict[str, Any]:
        def module_available(name: str) -> bool:
            try:
                return importlib.util.find_spec(name) is not None
            except ModuleNotFoundError:
                return False

        available_modules = {
            "agent_framework": module_available("agent_framework"),
            "agent_framework_foundry": module_available("agent_framework.foundry"),
            "agent_hooks": module_available("agent_hooks"),
            "azure_identity": module_available("azure.identity"),
        }
        return {
            "project_endpoint": self.settings.project_endpoint,
            "model": self.settings.model,
            "runtime_ready": all(available_modules.values()),
            "missing_modules": [name for name, available in available_modules.items() if not available],
            "synthetic_data_only": True,
        }

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            bank = self.bank.snapshot()
            events = [dict(event) for event in self._events]
            transactions = bank["transactions"]
            hook_events = [
                event
                for event in events
                if event["type"] == "hook_interception"
                and event.get("interception_point") == "pre_tool_call"
            ]
            latest_hook = hook_events[-1] if hook_events else None
            payment_events = [
                event for event in events if event["type"] == "payment_service_outcome"
            ]
            if transactions:
                outcome = "completed"
            elif self._run_status == "awaiting_approval":
                outcome = "awaiting_approval"
            elif latest_hook and latest_hook.get("verdict") == "deny":
                outcome = "blocked"
            elif payment_events and payment_events[-1].get("status") != "completed":
                outcome = "service_declined"
            elif self._run_status == "error":
                outcome = "error"
            elif self._run_status == "completed":
                outcome = "no_tool_invocation"
            else:
                outcome = "not_started"
            return {
                "scenario": self._scenario.public() if self._scenario else None,
                "run_status": self._run_status,
                "hooks_enabled": self.hooks_enabled,
                "correlation_id": self._correlation_id,
                "outcome": outcome,
                "no_money_moved": not transactions
                and bank["balance_cents"] == bank["initial_balance_cents"],
                "assistant_response": self._assistant_response,
                "error": dict(self._error) if self._error else None,
                "approval": dict(self._approval) if self._approval else None,
                "ledger": bank,
                "events": events,
            }

    def wait_for_completion(self, timeout: float = 10) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self._lock:
                if self._run_status in {"completed", "error", "idle"}:
                    return True
            time.sleep(0.01)
        return False

    def _run_live(self, scenario: Scenario) -> None:
        try:
            from .runtime import run_foundry_agent

            response = asyncio.run(run_foundry_agent(self, scenario))
        except Exception as exc:
            message = str(exc).strip() or "The agent runtime did not return a diagnostic message."
            with self._lock:
                self._error = {
                    "type": type(exc).__name__,
                    "message": message[:400],
                }
                self._run_status = "error"
                self._emit(
                    "agent_error",
                    error_type=type(exc).__name__,
                    message=message[:400],
                )
        else:
            text = getattr(response, "text", None)
            with self._lock:
                self._assistant_response = str(text) if text is not None else str(response)
                self._run_status = "completed"
                self._emit("agent_completed", response_received=True)
