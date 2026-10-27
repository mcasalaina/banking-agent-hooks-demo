from __future__ import annotations

import unittest

from banking_demo.domain import INITIAL_BALANCE_CENTS, PaymentPolicy, SyntheticBank


class PaymentPolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.bank = SyntheticBank()
        self.policy = PaymentPolicy(self.bank)

    def test_saved_beneficiary_routine_payment_is_allowed(self) -> None:
        decision = self.policy.evaluate("200.00", "saved-001")

        self.assertEqual("allow", decision.verdict)
        self.assertEqual("saved_beneficiary_within_limit", decision.reason)

    def test_high_value_new_beneficiary_requires_approval(self) -> None:
        decision = self.policy.evaluate("15000.00", "new-001")

        self.assertEqual("escalate", decision.verdict)
        self.assertEqual("transfer_requires_approval", decision.reason)

    def test_frozen_beneficiary_is_denied(self) -> None:
        decision = self.policy.evaluate("200.00", "frozen-001")

        self.assertEqual("deny", decision.verdict)
        self.assertEqual("beneficiary_frozen", decision.reason)

    def test_unknown_beneficiary_is_denied(self) -> None:
        decision = self.policy.evaluate("200.00", "claimed-verified-by-user")

        self.assertEqual("deny", decision.verdict)
        self.assertEqual("beneficiary_not_found", decision.reason)

    def test_invalid_amount_is_denied(self) -> None:
        for amount in ("0", "-10", "1.001", "not-money"):
            with self.subTest(amount=amount):
                self.assertEqual("deny", self.policy.evaluate(amount, "saved-001").verdict)


class PaymentServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.bank = SyntheticBank()

    def test_completed_payment_mutates_ledger_once(self) -> None:
        result = self.bank.execute_transfer("200.00", "saved-001", "invoice", "corr-1")

        self.assertEqual("completed", result["status"])
        self.assertEqual(INITIAL_BALANCE_CENTS - 20_000, self.bank.snapshot()["balance_cents"])
        self.assertEqual(1, len(self.bank.snapshot()["transactions"]))

    def test_frozen_beneficiary_is_rejected_by_service_too(self) -> None:
        result = self.bank.execute_transfer("200.00", "frozen-001", "", "corr-2")

        self.assertEqual("declined", result["status"])
        self.assertEqual("beneficiary_frozen", result["reason"])
        self.assertEqual(INITIAL_BALANCE_CENTS, self.bank.snapshot()["balance_cents"])
        self.assertEqual([], self.bank.snapshot()["transactions"])

    def test_reset_restores_synthetic_ledger(self) -> None:
        self.bank.execute_transfer("200.00", "saved-001", "", "corr-3")
        self.bank.reset()

        snapshot = self.bank.snapshot()
        self.assertEqual(INITIAL_BALANCE_CENTS, snapshot["balance_cents"])
        self.assertEqual([], snapshot["transactions"])


if __name__ == "__main__":
    unittest.main()
