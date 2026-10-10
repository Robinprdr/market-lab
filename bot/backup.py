"""Consistent SQLite snapshots; restoration never overwrites an existing file."""
import argparse
import os
from pathlib import Path
import sqlite3
import tempfile


def copy_database(source,destination):
    source,destination=Path(source),Path(destination)
    if not source.is_file():raise ValueError('Backup source missing')
    if destination.exists():raise ValueError('Destination exists; overwrite prohibited')
    destination.parent.mkdir(parents=True,exist_ok=True)
    fd,temp=tempfile.mkstemp(prefix='.sqlite-',dir=destination.parent);os.close(fd)
    try:
        src=sqlite3.connect('file:'+str(source.resolve())+'?mode=ro',uri=True)
        out=sqlite3.connect(temp)
        try:
            src.backup(out)
            if out.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('Invalid SQLite backup')
            out.commit()
        finally:out.close();src.close()
        os.chmod(temp,0o600)
        os.link(temp,destination) # Atomic publish; fails if another process created it.
    finally:Path(temp).unlink(missing_ok=True)
    return destination


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('backup','restore'))
    parser.add_argument('source',type=Path);parser.add_argument('destination',type=Path)
    args=parser.parse_args();copy_database(args.source,args.destination)
    print('SQLite '+args.action+': OK')


if __name__=='__main__':main()
