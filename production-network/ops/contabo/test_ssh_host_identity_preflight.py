"""Synthetic SSH host identity preflight tests; NEVER access live hosts."""
import base64
import hashlib
import subprocess
import unittest
from unittest.mock import patch
import ssh_host_identity_preflight as app

# RFC 5737 documentation address, not an actual Contabo endpoint.
IP = "198.51.100.55"
BLOB = b"\x00\x00\x00\x0bssh-ed25519\x00\x00\x00\x20" + b"\x11" * 32
ENCODED = base64.b64encode(BLOB).decode("ascii")
FP = "SHA256:" + base64.b64encode(hashlib.sha256(BLOB).digest()).decode("ascii").rstrip("=")


class SSHIdentityTests(unittest.TestCase):
    def record(self, host=IP):
        return f"{host} ssh-ed25519 {ENCODED}\n"

    def test_pinned_ed25519_success_is_observation_only(self):
        result = app._verify_keyscan_output(self.record(), IP, 22, FP)
        self.assertEqual(result["ssh_host_identity"],
                         "MATCHED_OUT_OF_BAND_ED25519_FINGERPRINT")
        self.assertEqual(result["remote_shell"], "NOT_ATTEMPTED")
        self.assertEqual(result["financial_mainnet"], "NOT_ACTIVE")

    def test_reject_wrong_fingerprint_without_leaking_public_key(self):
        with self.assertRaisesRegex(ValueError,"DOES NOT match") as context:
            app._verify_keyscan_output(self.record(), IP, 22, "SHA256:"+"A"*43)
        self.assertNotIn(ENCODED, str(context.exception))

    def test_reject_missing_wrong_host_duplicate_or_malformed_records(self):
        for output in ("", "# comment\n", self.record("198.51.100.66"),
                       self.record()*2 + f"{IP} ssh-ed25519 AAABBB\n",
                       f"{IP} ssh-rsa {ENCODED}\n",
                       f"{IP} ssh-ed25519 not-base64!\n",
                       f"{IP} ssh-ed25519 AAAA\n",
                       "unexpected record with four fields\n"):
            with self.assertRaises(ValueError, msg=output[:80]):
                app._verify_keyscan_output(output, IP, 22, FP)

    def test_one_key_may_have_duplicate_identical_records(self):
        result = app._verify_keyscan_output(self.record()*2, IP, 22, FP)
        self.assertEqual(result["remote_shell"], "NOT_ATTEMPTED")

    def test_nondefault_port_must_use_bracketed_host(self):
        host_record=f"[{IP}]:5901 ssh-ed25519 {ENCODED}\n"
        result=app._verify_keyscan_output(host_record,IP,5901,FP)
        self.assertEqual(result["port"],5901)
        with self.assertRaises(ValueError):
            app._verify_keyscan_output(self.record(),IP,5901,FP)

    def test_refuse_nonpublic_ip_and_malformed_arguments_before_network(self):
        for bad in ("127.0.0.1", "10.0.0.1", "192.168.1.1",
                    "198.51.100.1", "::1", "localhost", "1.2.3.4;echo pwned"):
            with self.assertRaises(ValueError, msg=bad):
                app.public_ipv4(bad)
        with patch.object(app.subprocess, "run", side_effect=AssertionError("network reached")):
            for fp in (None, "AA", "SHA256:bad", True):
                with self.assertRaises(ValueError):
                    app.preflight("8.8.8.8", fp)
            for port in (0,65536,"22",True):
                with self.assertRaises(ValueError):
                    app.preflight("8.8.8.8", FP, port=port)

    def test_no_password_login_or_ssh_execution(self):
        with patch.object(app.shutil, "which", return_value="/usr/bin/ssh-keyscan"):
            def fake_run(args, **kwargs):
                self.assertEqual(args[0], "/usr/bin/ssh-keyscan")
                self.assertEqual(args[-1], "8.8.8.8")
                self.assertEqual(args[args.index("-t")+1], "ed25519")
                self.assertFalse(any("password" in str(x).lower() for x in args))
                return subprocess.CompletedProcess(args, 0, self.record("8.8.8.8"), "")
            with patch.object(app.subprocess, "run", side_effect=fake_run):
                result=app.preflight("8.8.8.8", FP)
                self.assertEqual(result["host_changed"],False)
                self.assertEqual(result["remote_shell"],"NOT_ATTEMPTED")

    def test_refuse_network_failure_without_leaking_banners(self):
        with patch.object(app.shutil, "which", return_value="/usr/bin/ssh-keyscan"):
            with patch.object(app.subprocess,"run",
                              return_value=subprocess.CompletedProcess([],1,"","SECRET BANNER")):
                with self.assertRaises(ValueError) as context:
                    app.preflight("8.8.8.8", FP)
                self.assertNotIn("SECRET BANNER",str(context.exception))

    def test_scanned_key_cannot_self_attest(self):
        with patch.object(app.shutil,"which", return_value="/usr/bin/ssh-keyscan"):
            with patch.object(app.subprocess,"run",
                              return_value=subprocess.CompletedProcess([],0,self.record("8.8.8.8"),"")):
                with self.assertRaisesRegex(ValueError,"fingerprint"):
                    app.preflight("8.8.8.8", "not from VNC")


if __name__ == "__main__":
    unittest.main()
