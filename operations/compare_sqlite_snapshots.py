#!/usr/bin/env python3
"""Compare consistent offline SQLite backups. Reads only; emits no row values or secrets."""
import argparse
import base64
import hashlib
import json
import sqlite3
import sys
from pathlib import Path


def encode(value):
    if value is None:return ['null']
    if isinstance(value,bytes):return ['blob',base64.b64encode(value).decode('ascii')]
    if isinstance(value,int):return ['integer',str(value)]
    if isinstance(value,float):return ['real',value.hex()]
    if isinstance(value,str):return ['text',value]
    raise ValueError('unsupported SQLite value type')


def packed(value):
    return json.dumps(value,ensure_ascii=True,separators=(',',':')).encode('ascii')


def fingerprint(path,max_rows=100000):
    path=Path(path).resolve(strict=True)
    if not path.is_file():raise ValueError('snapshot must be a regular file')
    if max_rows<1:raise ValueError('max_rows must be positive')
    def verify_sidecars():
        for suffix in ('-wal','-journal'):
            sidecar=Path(str(path)+suffix)
            if sidecar.exists() and sidecar.stat().st_size:
                raise ValueError('use a consistent SQLite backup, not a database with active WAL/journal')
    verify_sidecars()
    before=path.stat()
    db=sqlite3.connect(path.as_uri()+'?mode=ro&immutable=1',uri=True)
    try:
        db.execute('PRAGMA query_only=ON')
        if db.execute('PRAGMA quick_check').fetchall()!=[('ok',)]:raise ValueError('SQLite integrity check failed')
        schema=db.execute("SELECT type,name,tbl_name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_stat%' ORDER BY type,name").fetchall()
        tables={}
        for kind,name,_,sql in schema:
            if kind!='table':continue
            # Quote identifiers from SQLite schema, never interpolate unchecked identifiers.
            quoted='"'+name.replace('"','""')+'"'
            rows=db.execute('SELECT * FROM '+quoted)
            hashes=[]
            for row in rows:
                if len(hashes)>=max_rows:raise ValueError('table exceeds bounded row limit')
                hashes.append(hashlib.sha256(b'privi-sqlite-row:v1\0'+packed([encode(v) for v in row])).digest())
            digest=hashlib.sha256(b'privi-sqlite-table:v1\0')
            for h in sorted(hashes):digest.update(h)
            tables[name]={'rows':len(hashes),'sha256':digest.hexdigest()}
        result={'schema_sha256':hashlib.sha256(packed(schema)).hexdigest(),'tables':tables}
    finally:db.close()
    verify_sidecars()
    after=path.stat()
    if (before.st_size,before.st_mtime_ns,before.st_ino)!=(after.st_size,after.st_mtime_ns,after.st_ino):raise ValueError('snapshot changed during comparison')
    return result


def compare(source,destination,max_rows=100000):
    if Path(source).resolve()==Path(destination).resolve():raise ValueError('source and destination must be distinct backup files')
    a,b=fingerprint(source,max_rows),fingerprint(destination,max_rows)
    differences=[]
    if a['schema_sha256']!=b['schema_sha256']:differences.append('schema differs')
    for table in sorted(set(a['tables'])|set(b['tables'])):
        if a['tables'].get(table)!=b['tables'].get(table):differences.append('table differs: '+table)
    return {'format':'privi-sqlite-snapshot-comparison/v1','status':'SNAPSHOT_CONTENT_MATCH' if not differences else 'MISMATCH','differences':differences,'source':a,'destination':b,'historical_migration_verified':False,'financial_mainnet_authorized':False,'note':'Content equality only. Independently authenticate backups, compare signing identities, ledger proofs and external dependencies. Row hashes are private operational metadata; keep this report private.'}


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('source',type=Path);p.add_argument('destination',type=Path)
    p.add_argument('--max-rows',type=int,default=100000)
    args=p.parse_args(argv)
    try:r=compare(args.source,args.destination,args.max_rows)
    except (OSError,ValueError,sqlite3.Error):
        print(json.dumps({'status':'BLOCKED','reason':'Cannot compare snapshots. Check file permissions, integrity, row limit and active WAL/journal. No data changed.'}))
        return 2
    print(json.dumps(r,indent=2));return 0 if r['status']=='SNAPSHOT_CONTENT_MATCH' else 1
if __name__=='__main__':sys.exit(main())
