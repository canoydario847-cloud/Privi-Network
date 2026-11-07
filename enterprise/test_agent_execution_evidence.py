import unittest
from agent_execution_evidence import issue_receipt, verify, verify_chain, receipt_hash

KEY = b"private-test-key-only-32-bytes-long!!"
def event(request="r1", auth="approved", execution="reported_success"):
    return dict(tenant="example", agent_id="agent-a", request_id=request,
                policy_version="v1", software_digest="sha256:demo",
                action="deploy", authorization=auth, execution=execution)

class ReceiptTests(unittest.TestCase):
    def test_valid_chain(self):
        first = issue_receipt(event(), KEY)
        second = issue_receipt(event("r2"), KEY, receipt_hash(first["receipt"]))
        self.assertTrue(verify_chain([first, second], KEY))
    def test_tamper_rejected(self):
        first = issue_receipt(event(), KEY)
        first["receipt"]["action"] = "transfer-funds"
        self.assertFalse(verify(first, KEY))
    def test_duplicate_request_rejected(self):
        first = issue_receipt(event(), KEY)
        second = issue_receipt(event(), KEY, receipt_hash(first["receipt"]))
        self.assertFalse(verify_chain([first, second], KEY))
    def test_denied_execution_rejected(self):
        with self.assertRaises(ValueError):
            issue_receipt(event(auth="denied"), KEY)
    def test_verified_requires_attestation(self):
        with self.assertRaises(ValueError):
            issue_receipt(event(execution="verified_success"), KEY)
    def test_missing_chain_member_rejected(self):
        first = issue_receipt(event(), KEY)
        second = issue_receipt(event("r2"), KEY, receipt_hash(first["receipt"]))
        self.assertFalse(verify_chain([second], KEY))

if __name__ == "__main__":
    unittest.main()
