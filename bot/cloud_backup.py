"""Daily consistent snapshot with 14-day local retention, no ledger replacement."""
from datetime import datetime, timezone
from pathlib import Path

from .backup import copy_database
from .cloud import cloud_settings


def main():
    cfg=cloud_settings();directory=cfg.db_path.parent/'backups'
    day=datetime.now(timezone.utc).date().isoformat()
    target=directory/('dry-run-'+day+'.sqlite')
    if not target.exists():copy_database(cfg.db_path,target)
    files=sorted(directory.glob('dry-run-????-??-??.sqlite'))
    for path in files[:-14]:path.unlink()
    print('DRY_RUN backup OK; retention 14 snapshots')


if __name__=='__main__':main()
