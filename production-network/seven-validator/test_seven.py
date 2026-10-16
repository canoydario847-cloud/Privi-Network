#!/usr/bin/env python3
"""Offline tests for exact 7-node isolated self-operated staging templates."""
import importlib.util
import sys
import unittest
from pathlib import Path
from unittest import mock

HERE=Path(__file__).parent
def module(name):
    s=importlib.util.spec_from_file_location(name,HERE/(name+".py"))
    m=importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m
compose=module("generate_compose")
audit=module("audit_seven")

class SevenNodeCompose(unittest.TestCase):
    def test_seven_unique_staging_validator_services(self):
        yaml=compose.render()
        self.assertEqual(7,sum(f"  validator{i}:" in yaml for i in range(7)))
        self.assertEqual(7,yaml.count("image: cosmos/evmd:privi-seven-v073"))
        self.assertEqual(7,yaml.count("    cap_drop:"))
        self.assertEqual(7,yaml.count("no-new-privileges:true"))
        self.assertIn("name: privi-seven-validator-stage",yaml)
        for i in range(7):
            self.assertIn(f"../.seven-validator-state/node{i}/evmd:/data/node{i}/evmd:rw",yaml)
            self.assertIn(f"127.0.0.1:{26657+10*i}:26657",yaml)
            self.assertIn(f"ipv4_address: 192.168.77.{10+i}",yaml)
            self.assertIn(f"ID: \"{i}\"",yaml)

    def test_zero_public_rpc_and_other_wallet_exposure(self):
        y=compose.render()
        self.assertEqual(1,y.count("127.0.0.1:8545:8545"))
        self.assertNotIn("0.0.0.0:26657",y)
        self.assertNotIn("0.0.0.0:8545",y)
        self.assertEqual(7,y.count("--minimum-gas-prices"))
        self.assertEqual(7,y.count("0.0001atest"))
        self.assertEqual(7,y.count("local-privi-seven-4221"))
        self.assertNotIn(" PRVI",y)  # no native PRVI token issued by staging compose

    def test_no_shared_validator_volume(self):
        y=compose.render()
        sources=[s for s in y.splitlines() if " - \"../.seven-validator-state/node" in s]
        self.assertEqual(7,len(sources))
        self.assertEqual(7,len(set(sources)))
        self.assertNotIn("testnet init-files",y)  # genesis generation is separate guarded setup

class SevenNodeAudit(unittest.TestCase):
    def test_reject_missing_endpoint(self):
        with self.assertRaisesRegex(ValueError,"Exactly seven"):
            audit.check(["http://localhost:26657"]*6)

    def test_reject_duplicate_endpoint(self):
        with self.assertRaisesRegex(ValueError,"DIFFERENT"):
            audit.check(["http://localhost:26657"]*7)

    def test_seven_votes_are_real(self):
        urls=[f"http://127.0.0.1:{26657+10*i}" for i in range(7)]
        addresses=[f"{i+1:040X}" for i in range(7)]
        peers={a:100 for a in addresses}
        expected={
            "nodes":7, "votingValidators":7, "blockHeight":42,
            "blockHash":"ABCD", "signedVotingPower":700,"totalVotingPower":700
        }
        commit={"signed_header":{"commit":{
            "signatures":[{"validator_address":a,"block_id_flag":2,"signature":"signed"}
                          for a in addresses]
        }}}
        with mock.patch.object(audit,"audit",return_value=expected),\
             mock.patch.object(audit,"validator_set",return_value=peers),\
             mock.patch.object(audit,"get",return_value=commit):
            result=audit.check(urls)
        self.assertEqual(7,result["distinctSigners"])
        self.assertIn("ONE operator",result["ownerIndependence"])

    def test_six_real_commit_signatures_do_not_pass(self):
        urls=[f"http://127.0.0.1:{26657+10*i}" for i in range(7)]
        addresses=[f"{i+1:040X}" for i in range(7)]
        peers={a:100 for a in addresses}
        expected={
            "nodes":7, "votingValidators":7, "blockHeight":42,
            "blockHash":"ABCD", "signedVotingPower":600,"totalVotingPower":700
        }
        commit={"signed_header":{"commit":{
            "signatures":[{"validator_address":a,"block_id_flag":2,"signature":"signed"}
                          for a in addresses[:6]]
        }}}
        with mock.patch.object(audit,"audit",return_value=expected),\
             mock.patch.object(audit,"validator_set",return_value=peers),\
             mock.patch.object(audit,"get",return_value=commit):
            with self.assertRaisesRegex(ValueError,"Only 6/7"):
                audit.check(urls)

if __name__=="__main__":unittest.main()
