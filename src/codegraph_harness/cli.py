"""Command-line entry point for the public harness."""

from __future__ import annotations

import json
import platform
import shutil
import subprocess
import sys
from collections.abc import Sequence


def _doctor() -> int:
    claude = shutil.which("claude")
    version: str | None = None
    if claude:
        completed = subprocess.run(
            [claude, "--version"],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if completed.returncode == 0:
            version = completed.stdout.strip()

    status = "success" if claude else "warning"
    payload = {
        "status": status,
        "summary": (
            "Claude Code is available"
            if claude
            else "Claude Code was not found on PATH"
        ),
        "next_actions": (
            []
            if claude
            else ["Install and authenticate Claude Code before evaluation."]
        ),
        "artifacts": [],
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "claude_path": claude,
            "claude_version": version,
        },
    }
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0 if claude else 2


def _usage() -> str:
    return (
        "usage: codegraph-harness <doctor|evaluate|bundle> [options]\n\n"
        "Commands:\n"
        "  doctor    Inspect the local evaluation prerequisites.\n"
        "  evaluate  Run a comparison suite without downloading vendors.\n"
        "  bundle    Build a deterministic offline ZIP.\n"
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    if not args or args[0] in {"-h", "--help"}:
        print(_usage())
        return 0

    command, *remainder = args
    if command == "doctor":
        return _doctor()
    if command == "evaluate":
        from codegraph_harness.evaluation import run_evaluation_cli

        return run_evaluation_cli(remainder)
    if command == "bundle":
        from codegraph_harness.bundle import run_bundle_cli

        return run_bundle_cli(remainder)

    print(f"Unknown command: {command}\n\n{_usage()}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
