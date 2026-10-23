"""Run the actual Ostiari Guard; the demo grants draft/proposal authority only."""
import tempfile
from pathlib import Path

from ostiari import Guard
from ostiari.exceptions import ActionBlockedError
from ostiari.models import OstiariConfig
from ostiari.storage import SQLiteBackend


class ManagedGuard:
    def __init__(self):
        self.directory = tempfile.TemporaryDirectory(prefix="workbench-guard-")
        self.storage = SQLiteBackend(path=str(Path(self.directory.name) / "traces.db"))
        self.guard = Guard(config=OstiariConfig(fail_open=False), storage=self.storage,
                           parameter_risk=True)
        self.guard.configure(Path(__file__).resolve().parents[1] / "config/governance.yaml")
        self.guard.start()

    def validate(self, *args, **kwargs):
        return self.guard.validate(*args, **kwargs)

    def shutdown(self):
        self.guard.shutdown()
        self.storage.close()
        self.directory.cleanup()


def create_guard() -> ManagedGuard:
    return ManagedGuard()


def validate(guard: ManagedGuard, action: str, params: dict | None = None) -> dict:
    try:
        result = guard.validate(action, params or {}, {"agent_id": "support-demo"})
        return {"engine": "Ostiari Guard", "action": action, "tier": result.tier,
                "score": result.score, "executed": False}
    except ActionBlockedError as exc:
        return {"engine": "Ostiari Guard", "action": action, "tier": "block",
                "score": exc.score, "executed": False}
