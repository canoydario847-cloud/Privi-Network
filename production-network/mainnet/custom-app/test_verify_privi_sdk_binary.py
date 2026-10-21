"""Mock-only tests: no SDK downloads, wallets, tokens, or running network."""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

SPEC = importlib.util.spec_from_file_location(
    "verify_privi_sdk_binary", Path(__file__).with_name("verify_privi_sdk_binary.py")
)
mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mod)


class ProvenanceTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name) / "privi-patched-sdk-app-only"
        self.root.mkdir()
        for rel, markers in mod.MARKERS.items():
            path = self.root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("\n".join(markers), encoding="utf-8")
        self.module = {
            "Path": mod.SDK,
            "Version": mod.VERSION,
            "Replace": {"Path": str(self.root), "Dir": str(self.root)},
        }
        self.binary = ("/tmp/privi-evmd: go1.25.9\n"
                       "\tpath\tgithub.com/cosmos/evm/evmd/cmd/evmd\n"
                       "\tmod\tgithub.com/cosmos/evm/evmd\t(devel)\n"
                       f"\tdep\t{mod.SDK}\t{mod.VERSION}\th1:example\n"
                       f"\t=>\t{self.root}\t(devel)\n")

    def check(self):
        return mod.verify(json.dumps(self.module), self.binary, self.root)

    def test_valid_pinned_module_with_all_guards(self):
        result = self.check()
        self.assertEqual(result["status"], "BUILD_ONLY_SDK_INPUT_VERIFIED")
        self.assertEqual(result["financial_mainnet"], "NO_GO")
        self.assertEqual(len(result["security_source_sha256"]), 3)

    def test_reject_module_graph_without_local_replace(self):
        self.module.pop("Replace")
        with self.assertRaisesRegex(ValueError, "module graph"):
            self.check()

    def test_reject_wrong_sdk_version(self):
        self.module["Version"] = "v0.54.4"
        with self.assertRaisesRegex(ValueError, "module/version"):
            self.check()

    def test_reject_binary_without_disposable_sdk_replace(self):
        self.binary = self.binary.replace("\t=>\t", "\twrong\t")
        with self.assertRaisesRegex(ValueError, "compiled binary"):
            self.check()

    def test_reject_binary_using_external_sdk_replace(self):
        self.binary = self.binary.replace(str(self.root), "/some/other/sdk")
        with self.assertRaisesRegex(ValueError, "compiled binary"):
            self.check()

    def test_reject_unsafe_unpatched_source(self):
        path = self.root / "x/bank/keeper/genesis.go"
        path.write_text("// unpatched SDK genesis", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "missing unique guard"):
            self.check()

    def test_reject_duplicate_guard_in_source(self):
        path = self.root / "x/bank/keeper/keeper.go"
        path.write_text(path.read_text() + "\n" + mod.MARKERS["x/bank/keeper/keeper.go"][0])
        with self.assertRaisesRegex(ValueError, "missing unique guard"):
            self.check()


if __name__ == "__main__":
    unittest.main()
