"""Built-in cursor harness adapter."""

from __future__ import annotations

import subprocess


class CursorHarness:
    """Invokes cursor CLI as harness adapter."""

    name = "cursor"

    def invoke(self, cmd: list[str]) -> int:
        result = subprocess.run(["cursor", *cmd])
        return result.returncode
