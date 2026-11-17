"""Ensure the offline customer report never destroys an existing file."""
import contextlib
import io
import json
import pathlib
import tempfile
import unittest

from pilot_report import main


class ReportNonDestructiveOutputTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = pathlib.Path(self.temp.name)
        self.source = self.folder / "consented-demo.json"
        self.source.write_text(
            json.dumps({"mode": "LOCAL_DEMO_NOT_ON_CHAIN",
                        "accepted": 0, "receipts": [], "rejected": []}),
            encoding="utf-8")

    def run_report(self, destination):
        with contextlib.redirect_stderr(io.StringIO()):
            return main([str(self.source), "--output", str(destination)])

    def test_new_file_is_created(self):
        output = self.folder / "new-report.txt"
        self.assertEqual(self.run_report(output), 0)
        self.assertIn("OFFLINE MILEAGE", output.read_text(encoding="utf-8"))

    def test_existing_report_is_not_overwritten(self):
        output = self.folder / "previous-report.txt"
        output.write_text("original customer report", encoding="utf-8")
        self.assertEqual(self.run_report(output), 2)
        self.assertEqual(output.read_text(encoding="utf-8"),
                         "original customer report")

    def test_symlink_to_existing_file_is_not_followed(self):
        protected = self.folder / "protected.txt"
        protected.write_text("private original data", encoding="utf-8")
        output = self.folder / "report.txt"
        try:
            output.symlink_to(protected)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks unavailable on this filesystem")
        self.assertEqual(self.run_report(output), 2)
        self.assertEqual(protected.read_text(encoding="utf-8"),
                         "private original data")
        self.assertTrue(output.is_symlink())

    def test_second_generation_requires_new_filename(self):
        output = self.folder / "first-report.txt"
        self.assertEqual(self.run_report(output), 0)
        first = output.read_bytes()
        self.assertEqual(self.run_report(output), 2)
        self.assertEqual(output.read_bytes(), first)

    def test_missing_parent_directory_is_not_created(self):
        output = self.folder / "missing" / "report.txt"
        self.assertEqual(self.run_report(output), 2)
        self.assertFalse(output.exists())

    def test_existing_directory_named_txt_is_not_replaced(self):
        output = self.folder / "directory.txt"
        output.mkdir()
        self.assertEqual(self.run_report(output), 2)
        self.assertTrue(output.is_dir())


if __name__ == "__main__":
    unittest.main()
