import copy
import json
import unittest
from pathlib import Path
from host_plan import inspect, pairs_unique

BASE = json.loads((Path(__file__).parent / 'candidate.json').read_text())

class ContaboPlanTests(unittest.TestCase):
    def test_draft_with_placeholders_is_structurally_valid_but_blocked(self):
        errors, blockers = inspect(BASE)
        self.assertEqual(errors, [])
        self.assertGreaterEqual(len(blockers), 24)

    def test_denies_live_financial_flags(self):
        for key in ('financial_mainnet_enabled', 'real_prvi_issuance_enabled', 'auto_provision_enabled'):
            sample = copy.deepcopy(BASE)
            sample[key] = True
            self.assertTrue(inspect(sample)[0], key)

    def test_duplicate_real_instance_refused(self):
        sample = copy.deepcopy(BASE)
        sample['nodes'][0]['instance_id'] = 'ctb-123'
        sample['nodes'][1]['instance_id'] = 'ctb-123'
        self.assertTrue(any('duplicate instance_id' in e for e in inspect(sample)[0]))

    def test_no_exposed_rpc(self):
        sample = copy.deepcopy(BASE)
        sample['nodes'][0]['rpc_bind'] = '0.0.0.0'
        self.assertTrue(any('loopback' in e for e in inspect(sample)[0]))

    def test_no_embedded_secret(self):
        sample = copy.deepcopy(BASE)
        sample['nodes'][0]['ssh_private_key'] = 'sensitive'
        self.assertTrue(inspect(sample)[0])

    def test_bad_or_private_public_ip(self):
        for ip in ('192.168.1.42', '127.0.0.1', 'garbage'):
            sample = copy.deepcopy(BASE)
            sample['nodes'][0]['public_ipv4'] = ip
            self.assertTrue(inspect(sample)[0], ip)

    def test_overlay_must_be_private(self):
        sample = copy.deepcopy(BASE)
        sample['nodes'][0]['private_overlay_ipv4'] = '8.8.8.8'
        self.assertTrue(inspect(sample)[0])

    def test_distinct_node_identity(self):
        sample = copy.deepcopy(BASE)
        sample['nodes'][1]['id'] = sample['nodes'][0]['id']
        self.assertTrue(inspect(sample)[0])

    def test_reject_duplicate_json_properties(self):
        with self.assertRaises(ValueError):
            json.loads('{"a":1,"a":2}', object_pairs_hook=pairs_unique)

    def test_validator_identity_malformed_never_crashes(self):
        for malformed in (None, [], ["privi-owner-val-01"], {}, {"bad": "value"},
                          42, True):
            sample = copy.deepcopy(BASE)
            sample["nodes"][0]["id"] = malformed
            errors, blockers = inspect(sample)
            self.assertTrue(any("invalid ID" in item for item in errors), malformed)
            self.assertTrue(any("node IDs" in item for item in errors), malformed)

    def test_ipv4_overlay_must_be_genuine_rfc1918(self):
        for invalid in ("192.0.0.9", "100.64.0.1", "169.254.0.9",
                        "127.0.0.2", "198.18.0.1", "224.0.0.1",
                        "0.0.0.0", "255.255.255.255"):
            sample = copy.deepcopy(BASE)
            sample["nodes"][0]["private_overlay_ipv4"] = invalid
            errors, _ = inspect(sample)
            self.assertTrue(any("RFC1918" in item for item in errors), invalid)

    def test_rfc1918_private_overlays_accepted(self):
        for ip in ("10.1.2.3","172.16.0.2","172.31.255.254","192.168.1.2"):
            sample=copy.deepcopy(BASE)
            sample["nodes"][0]["private_overlay_ipv4"]=ip
            errors, _ = inspect(sample)
            self.assertFalse(any("RFC1918" in item for item in errors), (ip, errors))

    def test_duplicate_key_error_does_not_echo_secret_property_name(self):
        sentinel="secret-production-password"
        raw=json.dumps({sentinel:1})[:-1]+', "'+sentinel+'":2}'
        with self.assertRaises(ValueError) as ctx:
            json.loads(raw,object_pairs_hook=pairs_unique)
        self.assertNotIn(sentinel,str(ctx.exception))

    def test_reject_fingerprint_wrong_shape(self):
        sample = copy.deepcopy(BASE)
        sample['nodes'][0]['admin_ssh_public_key_fingerprint'] = 'deadbeef'
        self.assertTrue(inspect(sample)[0])

if __name__ == '__main__':
    unittest.main()
