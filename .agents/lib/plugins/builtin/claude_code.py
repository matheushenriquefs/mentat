"""Built-in claude-code harness adapter."""

from __future__ import annotations

import subprocess


class ClaudeCodeHarness:
    """Invokes claude-code CLI as harness adapter."""

    name = "claude-code"

    def invoke(self, cmd: list[str]) -> int:
        result = subprocess.run(["claude", *cmd])
        return result.returncode
