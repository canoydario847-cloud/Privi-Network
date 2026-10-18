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

    def test_reject_fingerprint_wrong_shape(self):
        sample = copy.deepcopy(BASE)
        sample['nodes'][0]['admin_ssh_public_key_fingerprint'] = 'deadbeef'
        self.assertTrue(inspect(sample)[0])

if __name__ == '__main__':
    unittest.main()
