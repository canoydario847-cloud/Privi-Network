"""Unit tests for the fail-closed *build-only* custom app source patcher."""
import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("privi_cap_patch", HERE / "apply_prvi_cap.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

APP = '''package evmd
import (
    evmconfig "github.com/cosmos/evm/evmd/config"
)
type EVMD struct {
    BankKeeper            bankkeeper.Keeper
}
func test() {
    evmChainID := cast.ToUint64(appOpts.Get(srvflags.EVMChainID))
    encodingConfig := evmencoding.MakeConfig(evmChainID)
    keys := storetypes.NewKVStoreKeys(
        authtypes.StoreKey, banktypes.StoreKey, stakingtypes.StoreKey,
    )
    app.BankKeeper = bankkeeper.NewBaseKeeper(
        appCodec,
        runtime.NewKVStoreService(keys[banktypes.StoreKey]),
        app.AccountKeeper,
        evmconfig.BlockedAddresses(),
        authAddr,
        logger,
    )
    app.BankKeeper = app.BankKeeper.WithObjStoreKey(oKeys[banktypes.ObjectStoreKey])
    app.ModuleManager = module.NewManager(
        bank.NewAppModule(appCodec, app.BankKeeper, app.AccountKeeper, nil),
    )
    app.ModuleManager.SetOrderInitGenesis(genesisModuleOrder...)
    if err := app.UpgradeKeeper.SetModuleVersionMap(ctx, app.ModuleManager.GetVersionMap()); err != nil {
        panic(err)
    }

    return app.ModuleManager.InitGenesis(ctx, app.appCodec, genesisState)
}
func (app *EVMD) BeginBlocker(ctx sdk.Context) (sdk.BeginBlock, error) {
    return app.ModuleManager.BeginBlock(ctx)
}
func (app *EVMD) EndBlocker(ctx sdk.Context) (sdk.EndBlock, error) {
    return app.ModuleManager.EndBlock(ctx)
}
'''
APP = "\n".join(("\t" * ((len(line) - len(line.lstrip(" "))) // 4)) + line.lstrip(" ") for line in APP.split("\n"))

class PatcherTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.upstream = self.root / ".upstream-capbuild"
        (self.upstream / "evmd").mkdir(parents=True)
        self.repo = self.root / "source"
        source = self.repo / "production-network" / "mainnet" / "prvicap"
        source.mkdir(parents=True)
        (source / "keeper.go").write_text("package prvicap\n", encoding="utf-8")
        (source / "sdk_bank_adapter.go").write_text(
            "package prvicap\nfunc RestrictedBank(){}\n", encoding="utf-8"
        )
        (source / "chain_identity.go").write_text(
            "package prvicap\nfunc ValidateEVMChainID(id uint64) error { return nil }\n", encoding="utf-8"
        )
        self.app_file = self.upstream / "evmd" / "app.go"
        self.app_file.write_text(APP, encoding="utf-8")

    def test_rejects_unexpected_checkout(self):
        with self.assertRaisesRegex(ValueError, "non-disposable"):
            module.apply_patch(self.root, self.repo, verify_git=False)

    def test_rejects_unreviewed_upstream_source_without_partial_write(self):
        self.app_file.write_text(APP.replace("return app.ModuleManager.InitGenesis",
                                             "return app.UnknownGenesis"), encoding="utf-8")
        before = self.app_file.read_text()
        with self.assertRaisesRegex(ValueError, "pinned upstream mismatch"):
            module.apply_patch(self.upstream, self.repo, verify_git=False)
        self.assertEqual(before, self.app_file.read_text())
        self.assertFalse((self.upstream / "evmd" / "prvicap").exists())

    def test_rejects_duplicate_constructor(self):
        self.app_file.write_text(APP.replace("    app.BankKeeper = bankkeeper.NewBaseKeeper",
                                             "    app.BankKeeper = bankkeeper.NewBaseKeeper"), encoding="utf-8")
        app = self.app_file.read_text()
        app += '\n' + app[app.index("\tapp.BankKeeper = bankkeeper.NewBaseKeeper"):
                         app.index("\treturn app.ModuleManager.InitGenesis")]
        self.app_file.write_text(app)
        with self.assertRaisesRegex(ValueError, "pinned upstream mismatch"):
            module.apply_patch(self.upstream, self.repo, verify_git=False)

    def test_writes_restricted_bank_before_keeper_injection(self):
        result = module.apply_patch(self.upstream, self.repo, verify_git=False)
        app = self.app_file.read_text()
        self.assertEqual(result["status"], "BUILD_ONLY_PRVI_CONSENSUS_CAP_APP_SOURCE_WIRED")
        self.assertFalse(result["release_ready"])
        self.assertIn("prvicap.RestrictedBank(baseBank, app.PriviCapKeeper)", app)
        self.assertIn("bank.NewAppModule(appCodec,",app)
        self.assertIn("baseBank.WithMintCoinsRestriction(app.PriviCapKeeper.MintRestriction)",app)
        self.assertEqual(app.count("baseBank.WithMintCoinsRestriction(app.PriviCapKeeper.MintRestriction)"),1)
        self.assertNotIn("bank.NewAppModule(appCodec, app.BankKeeper,",app)
        self.assertLess(app.index("app.BankKeeper = prvicap.RestrictedBank("),
                        app.index("bank.NewAppModule("))
        self.assertLess(app.index("prvicap.RestrictedBank"), app.index("return app.ModuleManager.InitGenesis")
                        if "return app.ModuleManager.InitGenesis" in app else app.index("response, initErr"))
        self.assertIn("prvicap.StoreKey", app)
        self.assertIn("prvicap.ValidateEVMChainID(evmChainID)", app)
        self.assertIn("PRVI EIP-155 app identity rejected", app)
        self.assertLess(app.index("prvicap.ValidateEVMChainID(evmChainID)"), app.index("bankkeeper.NewBaseKeeper("))
        self.assertIn("func ValidateEVMChainID", (self.upstream/"evmd"/"prvicap"/"chain_identity.go").read_text())
        self.assertIn("prvicap.New(runtime.NewKVStoreService", app)
        self.assertIn("bankGenesis.Supply.AmountOf(prvicap.BaseDenom)", app)
        self.assertIn("prvicap.ValidateGenesisBase(initialPRVI.String())", app)
        self.assertIn("PRVI cap declared genesis denied before module init", app)
        self.assertIn("EVM gas denomination must be aprvi", app)
        self.assertIn("bonded staking denomination must be aprvi", app)
        self.assertIn("ZERO inflation and provisions", app)
        self.assertIn("aprvi requires 18 decimal PRVI metadata", app)
        self.assertIn("permissionless ERC20 registration forbidden", app)
        self.assertIn("aprvi ERC20 token pair forbidden", app)
        self.assertIn("erc20Genesis.Params.PermissionlessRegistration", app)
        self.assertIn("pair.Denom == prvicap.BaseDenom", app)
        self.assertLess(app.index("permissionless ERC20 registration forbidden"),
                        app.index("app.UpgradeKeeper.SetModuleVersionMap"))
        self.assertLess(app.index("aprvi ERC20 token pair forbidden"),
                        app.index("app.ModuleManager.InitGenesis(ctx, app.appCodec, genesisState)"))
        for tag in ("EVM gas denomination", "bonded staking denomination",
                    "ZERO inflation and provisions", "missing aprvi/PRVI metadata"):
            self.assertLess(app.index(tag),
                            app.index("app.UpgradeKeeper.SetModuleVersionMap"))
        self.assertLess(app.index("prvicap.ValidateGenesisBase"),
                        app.index("app.UpgradeKeeper.SetModuleVersionMap"))
        self.assertLess(app.index("app.UpgradeKeeper.SetModuleVersionMap"),
                        app.index("app.ModuleManager.InitGenesis(ctx, app.appCodec, genesisState)"))
        self.assertEqual(app.count("app.UpgradeKeeper.SetModuleVersionMap"),1)
        self.assertLess(app.index("prvicap.ValidateGenesisBase"),
                        app.index("app.ModuleManager.InitGenesis(ctx, app.appCodec, genesisState)"))
        self.assertLess(app.index("app.ModuleManager.InitGenesis(ctx, app.appCodec, genesisState)"),
                        app.index("app.PriviCapKeeper.InitGenesis"))

        self.assertIn("PRVI cap genesis initialization denied", app)
        self.assertIn("const StoreKey = \"prvicap\"", (self.upstream/"evmd"/"prvicap"/"store.go").read_text())
        self.assertNotIn("app.BankKeeper = app.BankKeeper.WithObjStoreKey", app)
        self.assertIn("PRVI beginning-of-block supply check denied", app)
        self.assertIn("PRVI end-of-block supply check denied", app)
        self.assertLess(app.index("PriviCapKeeper.Reconcile(ctx, app.BankKeeper)"),
                        app.index("return app.ModuleManager.BeginBlock(ctx)"))
        self.assertEqual(app.count("PriviCapKeeper.Reconcile(ctx, app.BankKeeper)"),2)
        self.assertIn("func (app *EVMD) CheckPriviNativeERC20Invariant(ctx sdk.Context) error", app)
        self.assertIn("app.Erc20Keeper.GetParams(ctx)", app)
        self.assertIn("app.Erc20Keeper.IsDenomRegistered(ctx, prvicap.BaseDenom)", app)
        self.assertIn("app.Erc20Keeper.GetTokenPairs(ctx)", app)
        self.assertEqual(app.count("app.CheckPriviNativeERC20Invariant(ctx)"), 3)
        for name in ("PRVI beginning-of-block ERC20 check denied",
                     "PRVI end-of-block ERC20 check denied",
                     "PRVI native genesis ERC20 runtime state denied"):
            self.assertIn(name, app)
        self.assertLess(app.index("PRVI beginning-of-block ERC20 check denied"),
                        app.index("return app.ModuleManager.BeginBlock(ctx)"))
        self.assertLess(app.index("PRVI native genesis ERC20 runtime state denied"),
                        app.index("return response, nil"))

    def test_rejects_unreviewed_second_base_keeper_constructor(self):
        # The old pinned bank assignment still patches exactly once, but an
        # unexpected *second* raw constructor would be a catastrophic alias risk.
        unreviewed = APP + "\nfunc rogue() { raw := bankkeeper.NewBaseKeeper(0); _ = raw }\n"
        self.app_file.write_text(unreviewed, encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "raw bank bypass risk"):
            module.apply_patch(self.upstream, self.repo, verify_git=False)
        self.assertEqual(self.app_file.read_text(encoding="utf-8"), unreviewed)
        self.assertFalse((self.upstream/"evmd"/"prvicap").exists())

    def test_rejects_unreviewed_bank_keeper_reassignment(self):
        unreviewed = APP + "\nfunc rogue() { app.BankKeeper = rogueKeeper }\n"
        self.app_file.write_text(unreviewed, encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "raw bank bypass risk"):
            module.apply_patch(self.upstream, self.repo, verify_git=False)
        self.assertEqual(self.app_file.read_text(encoding="utf-8"), unreviewed)
        self.assertFalse((self.upstream/"evmd"/"prvicap").exists())

    def test_changed_end_blocker_is_rejected_without_partial_write(self):
        changed=APP.replace("return app.ModuleManager.EndBlock(ctx)",
                            "return app.UnreviewedEndBlock(ctx)")
        self.app_file.write_text(changed, encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "post-block supply invariant"):
            module.apply_patch(self.upstream, self.repo, verify_git=False)
        self.assertEqual(self.app_file.read_text(), changed)
        self.assertFalse((self.upstream/"evmd"/"prvicap").exists())


    def test_cannot_overwrite_existing_cap_keeper_files(self):
        (self.upstream/"evmd"/"prvicap").mkdir()
        with self.assertRaisesRegex(ValueError, "overwrite"):
            module.apply_patch(self.upstream, self.repo, verify_git=False)

    def test_verifies_exact_tag_and_git_commit(self):
        def fake_git(args, text):
            if "status" in args:
                return ""
            if "describe" in args:
                return module.TAG + "\n"
            if "rev-parse" in args:
                return "not-the-reviewed-commit\n"
            raise AssertionError(args)
        with patch.object(module.subprocess, "check_output", side_effect=fake_git):
            with self.assertRaisesRegex(ValueError, "exact reviewed"):
                module.apply_patch(self.upstream, self.repo, verify_git=True)

if __name__ == "__main__":
    unittest.main()

    def test_bank_migration_exception_is_unique_and_mint_restricted(self):
        module.apply_patch(self.upstream, self.repo, verify_git=False)
        src = self.app_file.read_text(encoding="utf-8")
        self.assertEqual(src.count("bank.NewAppModule(appCodec,"),1)
        self.assertIn("baseBank.WithMintCoinsRestriction(app.PriviCapKeeper.MintRestriction)",src)
        self.assertEqual(src.count("baseBank.WithMintCoinsRestriction("),1)
        self.assertEqual(src.count("app.BankKeeper = prvicap.RestrictedBank("),1)

    def test_bank_migration_rejects_unreviewed_extra_raw_module_keeper(self):
        extra = APP.replace(
            "bank.NewAppModule(appCodec, app.BankKeeper, app.AccountKeeper, nil),",
            "bank.NewAppModule(appCodec, app.BankKeeper, app.AccountKeeper, nil),\n"
            "        rogue.NewAppModule(baseBank),"
        )
        self.app_file.write_text(extra,encoding="utf-8")
        original=self.app_file.read_text(encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "raw bank keeper leaked"):
            module.apply_patch(self.upstream, self.repo, verify_git=False)
        self.assertEqual(self.app_file.read_text(encoding="utf-8"),original)
