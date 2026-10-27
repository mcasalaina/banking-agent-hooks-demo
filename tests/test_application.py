from __future__ import annotations

import time
import unittest
from unittest.mock import patch

from agent_framework import ChatResponse, Content, Message
from agent_framework.foundry import FoundryChatClient

from banking_demo.application import DemoApplication, DemoBusyError
from banking_demo.config import Settings
from banking_demo.domain import INITIAL_BALANCE_CENTS, SCENARIOS


async def model_response(client, *, messages, options, stream=False, **kwargs):
    if any(content.type == "function_result" for message in messages for content in message.contents):
        return ChatResponse(messages=Message("assistant", ["The payment tool returned its result."]))
    prompt = next(message.text for message in messages if message.role == "user")
    scenario = next(item for item in SCENARIOS.values() if item.prompt == prompt)
    return ChatResponse(
        messages=Message(
            "assistant",
            [Content.from_function_call(
                "payment-call",
                "make_transfer",
                arguments={"amount": float(scenario.amount), "beneficiary_id": scenario.beneficiary_id},
            )],
        ),
    )


class DemoApplicationTests(unittest.TestCase):
    def setUp(self) -> None:
        model = patch.object(FoundryChatClient, "_inner_get_response", new=model_response)
        model.start()
        self.addCleanup(model.stop)
        self.application = DemoApplication(
            Settings(
                project_endpoint="https://example.invalid/api/projects/demo",
                model="demo",
                approval_timeout_seconds=3,
            ),
        )

    def wait_for_status(self, expected: str, timeout: float = 2) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.application.snapshot()["run_status"] == expected:
                return
            time.sleep(0.005)
        self.fail(f"Timed out waiting for status {expected!r}.")

    def test_routine_scenario_records_hook_then_posts_ledger(self) -> None:
        self.application.start_scenario("routine")
        self.assertTrue(self.application.wait_for_completion())
        snapshot = self.application.snapshot()

        self.assertEqual("completed", snapshot["outcome"])
        self.assertEqual(1, len(snapshot["ledger"]["transactions"]))
        event_types = [event["type"] for event in snapshot["events"]]
        self.assertLess(
            event_types.index("hook_interception"),
            event_types.index("payment_tool_started"),
        )
        self.assertIn("receipt_created", event_types)
        self.assertTrue(all(event["origin"] == "live" for event in snapshot["events"]))
        hook = self.pre_tool_event(snapshot)
        self.assertEqual("saved_beneficiary_within_limit", hook["reason"])
        self.assertGreater(hook["hook_sequence"], 0)
        self.assertTrue(hook["hook_session_id"])

    def test_frozen_scenario_blocks_before_payment_tool(self) -> None:
        self.application.start_scenario("frozen")
        self.assertTrue(self.application.wait_for_completion())
        snapshot = self.application.snapshot()

        self.assertEqual("blocked", snapshot["outcome"])
        self.assertTrue(snapshot["no_money_moved"])
        self.assertEqual(INITIAL_BALANCE_CENTS, snapshot["ledger"]["balance_cents"])
        self.assertEqual([], snapshot["ledger"]["transactions"])
        event_types = [event["type"] for event in snapshot["events"]]
        self.assertNotIn("payment_tool_started", event_types)
        hook = self.pre_tool_event(snapshot)
        self.assertEqual("deny", hook["verdict"])
        self.assertEqual("pre_tool_call", hook["interception_point"])

    def test_prompt_injection_does_not_change_frozen_record_decision(self) -> None:
        self.application.start_scenario("injection")
        self.assertTrue(self.application.wait_for_completion())
        snapshot = self.application.snapshot()

        hook = self.pre_tool_event(snapshot)
        self.assertEqual("deny", hook["verdict"])
        self.assertEqual("beneficiary_frozen", hook["reason"])
        self.assertEqual([], snapshot["ledger"]["transactions"])

    def test_approval_pauses_without_ledger_mutation_then_approves(self) -> None:
        self.application.start_scenario("approval")
        self.wait_for_status("awaiting_approval")

        pending = self.application.snapshot()
        self.assertEqual(INITIAL_BALANCE_CENTS, pending["ledger"]["balance_cents"])
        self.assertEqual([], pending["ledger"]["transactions"])
        self.assertEqual("pending", pending["approval"]["status"])
        self.assertNotIn(
            "payment_tool_started",
            [event["type"] for event in pending["events"]],
        )

        self.application.resolve_approval("approve")
        self.assertTrue(self.application.wait_for_completion())
        final = self.application.snapshot()
        self.assertEqual("completed", final["outcome"])
        self.assertEqual(1, len(final["ledger"]["transactions"]))
        self.assertEqual("approve", final["approval"]["status"])
        hook = self.pre_tool_event(final)
        self.assertEqual("allow", hook["verdict"])
        self.assertEqual("approval", hook["resolved_by"])

    def test_rejected_approval_leaves_ledger_unchanged(self) -> None:
        self.application.start_scenario("approval")
        self.wait_for_status("awaiting_approval")
        self.application.resolve_approval("reject")
        self.assertTrue(self.application.wait_for_completion())
        final = self.application.snapshot()

        self.assertEqual("blocked", final["outcome"])
        self.assertTrue(final["no_money_moved"])
        self.assertEqual(INITIAL_BALANCE_CENTS, final["ledger"]["balance_cents"])
        self.assertEqual([], final["ledger"]["transactions"])
        hook = self.pre_tool_event(final)
        self.assertEqual("deny", hook["verdict"])
        self.assertEqual("rejection", hook["resolved_by"])

    def test_reset_clears_events_and_restores_initial_state(self) -> None:
        self.application.start_scenario("routine")
        self.assertTrue(self.application.wait_for_completion())
        reset = self.application.reset()

        self.assertEqual("idle", reset["run_status"])
        self.assertEqual([], reset["events"])
        self.assertEqual(INITIAL_BALANCE_CENTS, reset["ledger"]["balance_cents"])
        self.assertEqual([], reset["ledger"]["transactions"])

    def test_changing_hooks_resets_completed_run_in_both_directions(self) -> None:
        for hooks_enabled in (False, True):
            with self.subTest(hooks_enabled=hooks_enabled):
                self.application.start_scenario("routine", hooks_enabled=not hooks_enabled)
                self.assertTrue(self.application.wait_for_completion())
                reset = self.application.reset(hooks_enabled=hooks_enabled)

                self.assertEqual(hooks_enabled, reset["hooks_enabled"])
                self.assertEqual("idle", reset["run_status"])
                self.assertIsNone(reset["scenario"])
                self.assertIsNone(reset["approval"])
                self.assertIsNone(reset["assistant_response"])
                self.assertIsNone(reset["error"])
                self.assertIsNone(reset["correlation_id"])
                self.assertEqual([], reset["events"])
                self.assertEqual(INITIAL_BALANCE_CENTS, reset["ledger"]["balance_cents"])
                self.assertEqual([], reset["ledger"]["transactions"])
                self.assertEqual(hooks_enabled, self.application.reset()["hooks_enabled"])

    def test_reset_rejects_invalid_hooks_setting_without_clearing_run(self) -> None:
        self.application.start_scenario("routine")
        self.assertTrue(self.application.wait_for_completion())
        before = self.application.snapshot()
        for value in ("false", 0, 1):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "boolean"):
                self.application.reset(hooks_enabled=value)
            self.assertEqual(before, self.application.snapshot())

    @staticmethod
    def pre_tool_event(snapshot):
        return next(
            event for event in snapshot["events"]
            if event["type"] == "hook_interception"
            and event["interception_point"] == "pre_tool_call"
        )

    def test_approval_timeout_blocks_payment(self) -> None:
        self.application = DemoApplication(Settings(
            project_endpoint="https://example.invalid/api/projects/demo",
            model="demo",
            approval_timeout_seconds=0.05,
        ))
        self.application.start_scenario("approval")
        self.assertTrue(self.application.wait_for_completion())
        final = self.application.snapshot()
        self.assertEqual("blocked", final["outcome"])
        self.assertEqual("timed_out", final["approval"]["status"])
        self.assertTrue(final["no_money_moved"])
        self.assertNotIn("payment_tool_started", [event["type"] for event in final["events"]])

    def test_model_failure_is_explicit_and_does_not_move_money(self) -> None:
        with patch.object(FoundryChatClient, "_inner_get_response", side_effect=RuntimeError("Model unavailable")):
            self.application.start_scenario("routine")
            self.assertTrue(self.application.wait_for_completion())
        final = self.application.snapshot()
        self.assertEqual("error", final["run_status"])
        self.assertIn("Model unavailable", final["error"]["message"])
        self.assertTrue(final["no_money_moved"])
        self.assertNotIn("payment_tool_started", [event["type"] for event in final["events"]])

    def test_interceptor_failure_blocks_payment(self) -> None:
        with patch.object(self.application.policy, "evaluate", side_effect=RuntimeError("Policy unavailable")):
            self.application.start_scenario("routine")
            self.assertTrue(self.application.wait_for_completion())
        final = self.application.snapshot()
        self.assertEqual("blocked", final["outcome"])
        self.assertEqual("deny", self.pre_tool_event(final)["verdict"])
        self.assertTrue(final["no_money_moved"])
        self.assertNotIn("payment_tool_started", [event["type"] for event in final["events"]])

    def test_hooks_off_does_not_construct_middleware_or_fabricate_records(self) -> None:
        with patch("agent_framework.create_agent_hooks_middleware", side_effect=AssertionError("Hooks must not be created")):
            self.application.start_scenario("routine", hooks_enabled=False)
            self.assertTrue(self.application.wait_for_completion())
        final = self.application.snapshot()
        self.assertFalse(final["hooks_enabled"])
        self.assertEqual("completed", final["outcome"])
        self.assertEqual(1, len(final["ledger"]["transactions"]))
        types = [event["type"] for event in final["events"]]
        self.assertIn("model_proposed_transfer", types)
        self.assertIn("payment_tool_started", types)
        self.assertNotIn("hook_interception", types)

    def test_hooks_off_skips_high_value_approval(self) -> None:
        self.application.start_scenario("approval", hooks_enabled=False)
        self.assertTrue(self.application.wait_for_completion())
        final = self.application.snapshot()
        self.assertEqual("completed", final["outcome"])
        self.assertEqual(3_500_000, final["ledger"]["balance_cents"])
        self.assertIsNone(final["approval"])
        self.assertNotIn("approval_requested", [event["type"] for event in final["events"]])

    def test_hooks_off_keeps_frozen_beneficiary_service_validation(self) -> None:
        for scenario_id in ("frozen", "injection"):
            with self.subTest(scenario_id=scenario_id):
                self.application.start_scenario(scenario_id, hooks_enabled=False)
                self.assertTrue(self.application.wait_for_completion())
                final = self.application.snapshot()
                self.assertEqual("service_declined", final["outcome"])
                self.assertTrue(final["no_money_moved"])
                types = [event["type"] for event in final["events"]]
                self.assertIn("payment_tool_started", types)
                self.assertIn("payment_service_outcome", types)
                self.assertNotIn("hook_interception", types)

    def test_hooks_can_be_reenabled_and_cannot_change_during_a_run(self) -> None:
        self.application.start_scenario("approval", hooks_enabled=False)
        self.assertTrue(self.application.wait_for_completion())
        self.application.start_scenario("approval", hooks_enabled=True)
        self.wait_for_status("awaiting_approval")
        with self.assertRaises(DemoBusyError):
            self.application.start_scenario("routine", hooks_enabled=False)
        with self.assertRaises(DemoBusyError):
            self.application.reset(hooks_enabled=False)
        self.assertTrue(self.application.snapshot()["hooks_enabled"])
        self.application.resolve_approval("reject")
        self.assertTrue(self.application.wait_for_completion())
        final = self.application.snapshot()
        self.assertEqual("deny", self.pre_tool_event(final)["verdict"])
        self.assertTrue(final["no_money_moved"])

    def test_hooks_flag_must_be_boolean(self) -> None:
        for value in ("false", 0, 1, None):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "boolean"):
                self.application.start_scenario("routine", hooks_enabled=value)


if __name__ == "__main__":
    unittest.main()
