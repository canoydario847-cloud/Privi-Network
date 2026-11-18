"""Static regression tests for the guided Privi ONE sandbox interface."""
import ast
from pathlib import Path
import unittest

SERVER = Path(__file__).with_name("server.py")
TREE = ast.parse(SERVER.read_text(encoding="utf-8"))
HTML = next(
    node.value.value for node in TREE.body
    if isinstance(node, ast.Assign)
    and any(isinstance(t, ast.Name) and t.id == "HTML" for t in node.targets)
    and isinstance(node.value, ast.Constant)
)


class GuidedExperienceTests(unittest.TestCase):
    def test_preset_examples_and_explicit_steps(self):
        for fragment in (
            'data-example="balanced"',
            'data-example="low-budget"',
            'data-example="no-approval"',
            "Run a guided simulation",
            "Nothing is sent to an external AI model",
        ):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, HTML)

    def test_accessible_status_and_receipt_disabled_until_available(self):
        self.assertIn('id="simStatus"', HTML)
        self.assertIn('role="status"', HTML)
        self.assertIn('aria-live="polite"', HTML)
        self.assertIn('id="verify" class="secondary" type="button" disabled', HTML)
        self.assertIn("verifyButton.disabled=!lastReceipt;", HTML)
        self.assertIn("simulateButton.disabled=true", HTML)
        self.assertIn("simulateButton.disabled=false", HTML)

    def test_client_validation_and_no_new_payment_calls(self):
        self.assertIn("Number.isSafeInteger(budget)", HTML)
        self.assertIn("budgetText.trim()===''", HTML)
        self.assertIn("task.length>10000", HTML)
        self.assertIn("/api/simulate-secure", HTML)
        self.assertIn("/api/verify", HTML)
        for forbidden in ("/api/pay", "/api/charge", "/api/token-transfer"):
            self.assertNotIn(forbidden, HTML)

    def test_clearly_labeled_sandbox_limitations(self):
        for fragment in ("Sandbox only", "made-up comparisons",
                         "not identity verification",
                         "not blockchain transactions",
                         "Do not enter secrets"):
            self.assertIn(fragment, HTML)


if __name__ == "__main__":
    unittest.main()
