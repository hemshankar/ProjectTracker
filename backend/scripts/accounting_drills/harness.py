"""Scratch stack for the Phase 8 launch drills: its own databases and its own accounting service process.
Nothing here touches the live databases: `guard()` refuses to run unless both are named zz_drill_*."""
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from types import SimpleNamespace

REPO = Path(__file__).resolve().parents[3]
CORE_DB, ACC_DB, PORT, KEY = "zz_drill_core", "zz_drill_accounting", 8299, "drill-key"
PRICES = '{"claude-sonnet-5": {"input_per_mtok": 3.0, "output_per_mtok": 15.0, "cache_read_per_mtok": 0.3, "cache_write_per_mtok": 3.75}}'


def configure_env() -> None:
    """Must run before `app` is imported: config reads the environment at import time."""
    os.environ.update({
        "MONGO_URI": "mongodb://localhost:27017", "MONGO_DB_NAME": CORE_DB,
        "ACCOUNTING_SERVICE_URL": f"http://127.0.0.1:{PORT}", "ACCOUNTING_SERVICE_KEY": KEY,
        "SPEND_COUNTERS_ENFORCED": "true", "OUTBOX_POLL_SECONDS": "0.2", "OUTBOX_MAX_BACKOFF_SECONDS": "2",
        "USAGE_FALLBACK_PATH": f"/tmp/{CORE_DB}_fallback.jsonl", "PRICING_OVERRIDES_JSON": PRICES,
        "ALERT_OUTBOX_AGE_SECONDS": "5", "ALERT_SERVICE_DOWN_SECONDS": "1", "RECONCILE_ENABLED": "false",
    })


def guard() -> None:
    from app import config
    assert config.MONGO_DB_NAME == CORE_DB and config.MONGO_URI.endswith("localhost:27017"), "refusing: not the scratch DB"


class ScratchService:
    """The real accounting service app, run as a subprocess against the scratch database."""

    def __init__(self):
        self._proc = None
        self._python = os.environ["DRILL_ACCOUNTING_PYTHON"]
        self.env = {**os.environ, "MONGO_URI": "mongodb://localhost:27017", "MONGO_DB_NAME": ACC_DB,
                    "ACCOUNTING_SERVICE_KEY": KEY, "ROLLUP_VERIFY_ENABLED": "false"}

    def start(self) -> None:
        self._proc = subprocess.Popen(
            [self._python, "-m", "uvicorn", "app.main:app", "--port", str(PORT), "--log-level", "warning"],
            cwd=REPO / "accounting-service", env=self.env, stdout=sys.stderr, stderr=sys.stderr)
        for _ in range(100):
            try:
                if urllib.request.urlopen(f"http://127.0.0.1:{PORT}/health/ready", timeout=1).status == 200:
                    return
            except Exception:
                time.sleep(0.1)
        raise RuntimeError("scratch accounting service did not become ready")

    def stop(self) -> None:
        if self._proc:
            self._proc.terminate()
            self._proc.wait(10)
            self._proc = None

    def cli(self, *args: str) -> tuple:
        """Run the service's operator CLI (e.g. `rollups verify`) against the scratch database."""
        p = subprocess.run([self._python, "-m", "app.cli", *args], cwd=REPO / "accounting-service", env=self.env,
                           capture_output=True, text=True)
        return p.returncode, (p.stdout + p.stderr).strip()


def fake_response(model: str = "claude-sonnet-5", inp: int = 1200, out: int = 300, cache_read: int = 0):
    usage = SimpleNamespace(input_tokens=inp, output_tokens=out, cache_read_input_tokens=cache_read,
                            cache_creation_input_tokens=0, server_tool_use=None)
    return SimpleNamespace(model=model, usage=usage, _request_id="req_drill", content=[])


async def reset_databases() -> None:
    from motor.motor_asyncio import AsyncIOMotorClient
    client = AsyncIOMotorClient("mongodb://localhost:27017")
    for name in (CORE_DB, ACC_DB):
        assert name.startswith("zz_drill")
        await client.drop_database(name)
    client.close()


class Results:
    def __init__(self):
        self.rows = []

    def check(self, gate: str, name: str, ok: bool, detail: str = "") -> bool:
        self.rows.append((gate, name, bool(ok), detail))
        print(f"  [{'PASS' if ok else 'FAIL'}] {gate} {name}" + (f": {detail}" if detail else ""), flush=True)
        return ok

    @property
    def all_passed(self) -> bool:
        return all(r[2] for r in self.rows)
