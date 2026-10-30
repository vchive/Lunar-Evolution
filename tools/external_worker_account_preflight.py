"""Explicit read-only entry point; no worker/channel defaults are changed."""
from lunar_evolution.external_worker_account_preflight import main

if __name__ == "__main__":
    raise SystemExit(main())
