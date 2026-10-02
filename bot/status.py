"""Local status; never connects to IBKR or changes orders."""
import json
from .config import from_env
from .storage import Store


def main():
    settings=from_env();store=Store(settings.db_path)
    try:print(json.dumps(store.summary(),indent=2,default=str))
    finally:store.close()


if __name__=='__main__':main()
