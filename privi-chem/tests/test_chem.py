import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from server import ChemStore, ChemError, SHA, CANON, bearer_owner

SOURCE_HASH = hashlib.sha256(b"source laboratory PDF").hexdigest()
CODE_HASH = hashlib.sha256(b"simulation code v1").hexdigest()

class ChemTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.store=ChemStore(str(Path(self.tmp.name)/"chem.db"))
        self.owner=SHA("customer-one")
        self.pid=self.store.create(self.owner,{"title":"Safe aqueous sample comparison","formula":"H2O"})["project_id"]
    def tearDown(self):
        self.tmp.cleanup()
    def entry(self, source_type="simulation"):
        return {"source_type":source_type,"method":"instrument-calibration" if source_type=="measurement" else "numerical-simulation-v1",
                "data":{"temperature":{"value":298.15,"unit":"K"},"pH":{"value":7.1,"unit":"pH"}},
                "source_sha256":SOURCE_HASH,"code_sha256":CODE_HASH if source_type=="simulation" else None,
                "notes":"Fictional test data, not experimentally verified"}
    def test_simulation_and_measurement_are_distinct_and_hash_chained(self):
        first=self.store.add(self.owner,self.pid,self.entry("simulation"))
        second=self.store.add(self.owner,self.pid,self.entry("measurement"))
        self.assertEqual(second["previous_sha256"],first["chain_sha256"])
        r=self.store.report(self.owner,self.pid)
        self.assertEqual((r["report"]["simulation_count"],r["report"]["measurement_count"]),(1,1))
        self.assertEqual(r["report_sha256"],SHA(CANON(r["report"])))
        self.assertEqual(r["blockchain_anchor_status"],"not_submitted")
        token=self.store.token(self.owner,first["token_id"])
        self.assertFalse(token["minted_on_chain"])
        self.assertEqual(token["payload_sha256"],first["payload_sha256"])
        self.assertIsNone(self.store.token(SHA("another customer"),first["token_id"]))
    def test_evidence_persists_and_owner_isolation(self):
        eid=self.store.add(self.owner,self.pid,self.entry())
        reopened=ChemStore(str(Path(self.tmp.name)/"chem.db"))
        self.assertEqual(reopened.report(self.owner,self.pid)["report"]["entries"][0]["token_id"],eid["token_id"])
        self.assertIsNone(reopened.report(SHA("intruder"),self.pid))
        self.assertIsNone(reopened.add(SHA("intruder"),self.pid,self.entry()))
    def test_rejects_invalid_types_nonfinite_values_and_unhashed_sources(self):
        bad=self.entry()
        bad["source_type"]="verified_lab"  # cannot falsely mark simulation as laboratory proof
        with self.assertRaises(ChemError):self.store.add(self.owner,self.pid,bad)
        bad=self.entry()
        bad["data"]["temperature"]["value"]=float("nan")
        with self.assertRaises(ChemError):self.store.add(self.owner,self.pid,bad)
        bad=self.entry()
        bad["source_sha256"]=None
        with self.assertRaises(ChemError):self.store.add(self.owner,self.pid,bad)
        with self.assertRaises(ChemError):
            self.store.create(self.owner,{"title":"Untrusted input","formula":"H2O; DROP TABLE projects"})
    def test_bearer_tokens_required(self):
        from email.message import Message
        prev=os.environ.get("PRIVI_CHEM_API_KEYS")
        try:
            os.environ.pop("PRIVI_CHEM_API_KEYS",None)
            m=Message()
            m["Authorization"]="Bearer key"
            self.assertEqual(bearer_owner(m),(None,503))
            os.environ["PRIVI_CHEM_API_KEYS"]="key-one,key-two"
            self.assertEqual(bearer_owner(m),(None,401))
            m.replace_header("Authorization","Bearer key-two")
            self.assertEqual(bearer_owner(m),(SHA("key-two"),200))
        finally:
            if prev is None:os.environ.pop("PRIVI_CHEM_API_KEYS",None)
            else:os.environ["PRIVI_CHEM_API_KEYS"]=prev

if __name__=="__main__":unittest.main()
