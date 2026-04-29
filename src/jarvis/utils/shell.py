from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


@dataclass
class ShellResult:
    ok: bool
    code: int
    stdout: str
    stderr: str


def run_command(args: Sequence[str], timeout: int = 20, cwd: str | Path | None = None) -> ShellResult:
    try:
        proc = subprocess.run(
            list(args),
            cwd=str(cwd) if cwd else None,
            text=True,
            capture_output=True,
            timeout=timeout,
        )
        return ShellResult(proc.returncode == 0, proc.returncode, proc.stdout.strip(), proc.stderr.strip())
    except subprocess.TimeoutExpired as exc:
        return ShellResult(False, 124, exc.stdout or '', f'Timeout después de {timeout}s')
    except FileNotFoundError as exc:
        return ShellResult(False, 127, '', str(exc))
    except Exception as exc:
        return ShellResult(False, 1, '', str(exc))
