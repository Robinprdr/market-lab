"""Local status; never connects to IBKR or changes orders."""
import json
from .config import from_env
from .monitoring import dashboard_data
from .storage import Store


def main():
    settings=from_env();store=Store(settings.db_path)
    try:print(json.dumps(dashboard_data(store,settings),indent=2,default=str))
    finally:store.close()


if __name__=='__main__':main()
