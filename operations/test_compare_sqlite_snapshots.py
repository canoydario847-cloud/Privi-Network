import importlib.util
import sqlite3
import tempfile
import unittest
from pathlib import Path
spec=importlib.util.spec_from_file_location('snapshots',Path(__file__).with_name('compare_sqlite_snapshots.py'))
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class Snapshots(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.a=Path(self.tmp.name)/'source.db';self.b=Path(self.tmp.name)/'target.db'
        for path in (self.a,self.b):
            with sqlite3.connect(path) as c:
                c.execute('CREATE TABLE users (id INTEGER PRIMARY KEY, email TEXT, secret BLOB)')
                c.execute('INSERT INTO users VALUES(1,?,?)',('synthetic@example.invalid',b'private-test-value'))
    def test_equal_backups_match_without_exposing_rows_or_authorizing_migration(self):
        r=m.compare(self.a,self.b)
        self.assertEqual(r['status'],'SNAPSHOT_CONTENT_MATCH')
        self.assertFalse(r['historical_migration_verified']);self.assertFalse(r['financial_mainnet_authorized'])
        self.assertNotIn('synthetic@example.invalid',str(r));self.assertNotIn('private-test-value',str(r))
    def test_same_count_changed_row_is_detected(self):
        with sqlite3.connect(self.b) as c:c.execute("UPDATE users SET email='changed@example.invalid'")
        self.assertEqual(m.compare(self.a,self.b)['status'],'MISMATCH')
    def test_missing_table_is_detected(self):
        with sqlite3.connect(self.b) as c:c.execute('DROP TABLE users')
        self.assertIn('table differs: users',m.compare(self.a,self.b)['differences'])
    def test_empty_or_invalid_file_cannot_falsely_match(self):
        self.b.write_bytes(b'not a SQLite backup')
        with self.assertRaises(sqlite3.Error):m.compare(self.a,self.b)
    def test_live_wal_is_rejected(self):
        Path(str(self.a)+'-wal').write_bytes(b'pending writes')
        with self.assertRaisesRegex(ValueError,'WAL'):m.compare(self.a,self.b)
    def test_same_path_rejected(self):
        with self.assertRaises(ValueError):m.compare(self.a,self.a)
    def test_row_limit_fails_closed(self):
        with sqlite3.connect(self.a) as c:c.execute('INSERT INTO users VALUES(2,NULL,NULL)')
        with self.assertRaisesRegex(ValueError,'row limit'):m.compare(self.a,self.b,1)
    def test_reads_do_not_modify_files(self):
        a,b=self.a.read_bytes(),self.b.read_bytes();m.compare(self.a,self.b)
        self.assertEqual(a,self.a.read_bytes());self.assertEqual(b,self.b.read_bytes())
if __name__=='__main__':unittest.main()
