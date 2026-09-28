"""The deployed API must not accept requests before migrations succeed."""

import os
import subprocess
from pathlib import Path

import pytest


@pytest.mark.parametrize("migration_exit", [0, 1])
def test_entrypoint_runs_migrations_before_server(tmp_path, migration_exit):
    """A failed migration aborts startup while success preserves server arguments."""
    log = tmp_path / "calls"
    for name, body in {
        "python": f'#!/bin/sh\necho "migration $*" >> "$CALL_LOG"\nexit {migration_exit}\n',
        "server": '#!/bin/sh\necho "server $*" >> "$CALL_LOG"\n',
    }.items():
        executable = tmp_path / name
        executable.write_text(body)
        executable.chmod(0o755)
    entrypoint = Path(__file__).resolve().parents[2] / "deployment/start-api.sh"
    result = subprocess.run(
        ["/bin/sh", str(entrypoint), "server", "--port", "8000"],
        env={**os.environ, "PATH": str(tmp_path), "CALL_LOG": str(log)},
        check=False,
        timeout=10,
    )
    assert result.returncode == migration_exit
    calls = log.read_text().splitlines()
    assert calls[0] == "migration -m scripts.migrate_conversations"
    assert calls[1:] == (["server --port 8000"] if migration_exit == 0 else [])
