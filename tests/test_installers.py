"""Offline installer regression tests.

The macOS entry point is exercised against a real ZIP and a fake ``claude``
command.  PowerShell gets the same execution path when ``pwsh`` is available;
otherwise static assertions still protect its integrity, verification, and
rollback contract on macOS CI runners.
"""

from __future__ import annotations

import json
import hashlib
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
import zipfile

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from codegraph_harness.bundle import build_bundle

PUBLIC_PROFILE = PROJECT_ROOT / "packaging" / "profiles" / "public.json"


class OfflineInstallerTestCase(unittest.TestCase):
    """Create an extracted public bundle and an isolated fake Claude Code."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.work = Path(self.temp_dir.name)
        self.archive = self.work / "codegraph-harness-test.zip"
        build_bundle(
            PROJECT_ROOT,
            self.archive,
            version="0.1.0-test",
            profile_path=PUBLIC_PROFILE,
        )
        self.bundle = self.work / "bundle"
        with zipfile.ZipFile(self.archive) as contents:
            contents.extractall(self.bundle)

        self.config_root = self.work / "claude-config"
        self.codex_skill_root = self.work / "agents" / "skills"
        self.data_root = self.work / "data"
        self.state_root = self.work / "state"
        self.allowed_root = self.work / "approved-public-fixtures"
        self.allowed_root.mkdir()
        self.fake_log = self.work / "fake-claude.log"
        self.fake_codex_log = self.work / "fake-codex.log"
        self.fake_cli_state = self.work / "fake-cli-state"
        self.fake_bin = self.work / "bin"
        self.fake_bin.mkdir()
        self._make_fake_claude()
        self._make_fake_codex()

    def _make_fake_claude(self) -> None:
        if os.name == "nt":
            program = self.fake_bin / "claude.cmd"
            program.write_text(
                """@echo off
setlocal EnableExtensions
echo %*>> "%CODEGRAPH_FAKE_CLAUDE_LOG%"
if /I "%~1"=="mcp" if /I "%~2"=="get" (
  if not exist "%CODEGRAPH_FAKE_CLI_STATE%\\claude-mcp" exit /b 1
  type "%CODEGRAPH_FAKE_CLI_STATE%\\claude-mcp"
  exit /b 0
)
if /I "%~1"=="mcp" if /I "%~2"=="add" (
  if not exist "%CODEGRAPH_FAKE_CLI_STATE%" mkdir "%CODEGRAPH_FAKE_CLI_STATE%"
  echo %*> "%CODEGRAPH_FAKE_CLI_STATE%\\claude-mcp"
  exit /b 0
)
if /I "%~1"=="mcp" if /I "%~2"=="remove" (
  del /Q "%CODEGRAPH_FAKE_CLI_STATE%\\claude-mcp" 2>nul
  exit /b 0
)
exit /b 0
""",
                encoding="utf-8",
            )
            return
        program = self.fake_bin / "claude"
        program.write_text(
            """#!/usr/bin/env bash
set -eu
printf '%s\n' "$*" >> "$CODEGRAPH_FAKE_CLAUDE_LOG"
case "$*" in *"${CODEGRAPH_FAKE_CLAUDE_FAIL_ON:-__never__}"*) exit 9 ;; esac
if [ "${1:-}" = "mcp" ] && [ "${2:-}" = "get" ]; then
  [ -f "$CODEGRAPH_FAKE_CLI_STATE/claude-mcp" ] || exit 1
  cat "$CODEGRAPH_FAKE_CLI_STATE/claude-mcp"
elif [ "${1:-}" = "mcp" ] && [ "${2:-}" = "add" ]; then
  mkdir -p "$CODEGRAPH_FAKE_CLI_STATE"
  printf '%s\n' "$*" > "$CODEGRAPH_FAKE_CLI_STATE/claude-mcp"
elif [ "${1:-}" = "mcp" ] && [ "${2:-}" = "remove" ]; then
  rm -f "$CODEGRAPH_FAKE_CLI_STATE/claude-mcp"
fi
""",
            encoding="utf-8",
        )
        program.chmod(program.stat().st_mode | stat.S_IXUSR)

    def _make_fake_codex(self) -> None:
        if os.name == "nt":
            program = self.fake_bin / "codex.cmd"
            program.write_text(
                """@echo off
setlocal EnableExtensions
echo %*>> "%CODEGRAPH_FAKE_CODEX_LOG%"
if /I "%~1"=="mcp" if /I "%~2"=="get" (
  if not exist "%CODEGRAPH_FAKE_CLI_STATE%\\codex-mcp" exit /b 1
  type "%CODEGRAPH_FAKE_CLI_STATE%\\codex-mcp"
  exit /b 0
)
if /I "%~1"=="mcp" if /I "%~2"=="add" (
  if not exist "%CODEGRAPH_FAKE_CLI_STATE%" mkdir "%CODEGRAPH_FAKE_CLI_STATE%"
  echo %*> "%CODEGRAPH_FAKE_CLI_STATE%\\codex-mcp"
  exit /b 0
)
if /I "%~1"=="mcp" if /I "%~2"=="remove" (
  del /Q "%CODEGRAPH_FAKE_CLI_STATE%\\codex-mcp" 2>nul
  exit /b 0
)
exit /b 0
""",
                encoding="utf-8",
            )
            return
        program = self.fake_bin / "codex"
        program.write_text(
            """#!/usr/bin/env bash
set -eu
printf '%s\n' "$*" >> "$CODEGRAPH_FAKE_CODEX_LOG"
case "$*" in *"${CODEGRAPH_FAKE_CODEX_FAIL_ON:-__never__}"*) exit 9 ;; esac
if [ "${1:-}" = "mcp" ] && [ "${2:-}" = "get" ]; then
  [ -f "$CODEGRAPH_FAKE_CLI_STATE/codex-mcp" ] || exit 1
  cat "$CODEGRAPH_FAKE_CLI_STATE/codex-mcp"
elif [ "${1:-}" = "mcp" ] && [ "${2:-}" = "add" ]; then
  mkdir -p "$CODEGRAPH_FAKE_CLI_STATE"
  printf '%s\n' "$*" > "$CODEGRAPH_FAKE_CLI_STATE/codex-mcp"
elif [ "${1:-}" = "mcp" ] && [ "${2:-}" = "remove" ]; then
  rm -f "$CODEGRAPH_FAKE_CLI_STATE/codex-mcp"
fi
""",
            encoding="utf-8",
        )
        program.chmod(program.stat().st_mode | stat.S_IXUSR)

    def _environment(self) -> dict[str, str]:
        environment = os.environ.copy()
        environment.update(
            {
                "CODEGRAPH_ALLOW_TEST_OS": "1",
                "CLAUDE_CONFIG_DIR": str(self.config_root),
                "CODEGRAPH_DATA_ROOT": str(self.data_root),
                "CODEGRAPH_STATE_ROOT": str(self.state_root),
                "CODEGRAPH_FAKE_CLAUDE_LOG": str(self.fake_log),
                "CODEGRAPH_FAKE_CODEX_LOG": str(self.fake_codex_log),
                "CODEGRAPH_FAKE_CLI_STATE": str(self.fake_cli_state),
                "CODEGRAPH_CODEX_SKILLS_ROOT": str(self.codex_skill_root),
                "CODEGRAPH_TEST_PLATFORM": "macos",
                "CODEGRAPH_TEST_ARCH": "arm64",
                "PATH": str(self.fake_bin) + os.pathsep + environment.get("PATH", ""),
            }
        )
        return environment

    def _run_shell(
        self, script: str, *arguments: str, check: bool = True
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", str(self.bundle / script), *arguments],
            cwd=self.bundle,
            env=self._environment(),
            text=True,
            capture_output=True,
            check=check,
        )

    def _install_args(self) -> list[str]:
        return [
            "--claude-config-dir",
            str(self.config_root),
            "--data-root",
            str(self.data_root),
            "--state-root",
            str(self.state_root),
            "--codex-skill-root",
            str(self.codex_skill_root),
            "--allowed-root",
            str(self.allowed_root),
        ]

    def _use_runtime_bundle(
        self, selected_runtime: str = "macos-arm64"
    ) -> tuple[bytes, bytes]:
        vendor_dir = self.work / "vendor"
        vendor_dir.mkdir()
        runtimes: list[dict[str, object]] = []
        selected_gateway = b""
        selected_backend = b""
        for platform, arch, suffix in (
            ("macos", "arm64", ""),
            ("macos", "x86_64", ""),
            ("windows", "arm64", ".exe"),
            ("windows", "x86_64", ".exe"),
        ):
            runtime_id = f"{platform}-{arch}"
            gateway_bytes = (
                f"gateway-{runtime_id} CODEGRAPH_APPROVED_FIXTURES:{'a' * 64}:END"
            ).encode()
            backend_bytes = f"backend-{runtime_id}".encode()
            if runtime_id == selected_runtime:
                selected_gateway = gateway_bytes
                selected_backend = backend_bytes
            files = []
            for component, filename, content, version, commit, license_id in (
                (
                    "gateway",
                    f"codegraph-gateway{suffix}",
                    gateway_bytes,
                    "1.0.0",
                    "1" * 40,
                    "Apache-2.0",
                ),
                (
                    "backend",
                    f"codebase-memory-mcp{suffix}",
                    backend_bytes,
                    "0.10.8",
                    "2" * 40,
                    "MIT",
                ),
            ):
                source = f"{runtime_id}/{filename}"
                source_path = vendor_dir / source
                source_path.parent.mkdir(parents=True, exist_ok=True)
                source_path.write_bytes(content)
                files.append(
                    {
                        "component": component,
                        "source": source,
                        "target": f"runtime/{runtime_id}/bin/{filename}",
                        "sha256": hashlib.sha256(content).hexdigest(),
                        "version": version,
                        "commit": commit,
                        "license": license_id,
                        "executable": True,
                    }
                )
            runtimes.append({"platform": platform, "arch": arch, "files": files})
        profile = self.work / "runtime-profile.json"
        profile.write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "profile_id": "runtime-test",
                    "kind": "internal",
                    "description": "runtime fixture",
                    "approved_fixture_manifests": ["a" * 64],
                    "vendor_files": [],
                    "runtimes": runtimes,
                }
            ),
            encoding="utf-8",
        )
        build_bundle(
            PROJECT_ROOT,
            self.archive,
            version="0.2.0-test",
            profile_path=profile,
            vendor_dir=vendor_dir,
        )
        shutil.rmtree(self.bundle)
        with zipfile.ZipFile(self.archive) as contents:
            contents.extractall(self.bundle)
        return selected_gateway, selected_backend


@unittest.skipIf(
    os.name == "nt",
    "macOS installer tests require a POSIX path environment",
)
class MacOSInstallerTests(OfflineInstallerTestCase):
    def test_endpoint_scripts_have_no_network_or_package_manager_commands(self) -> None:
        combined = "\n".join(
            (
                (PROJECT_ROOT / "installers" / "macos" / "install.sh").read_text(),
                (PROJECT_ROOT / "installers" / "macos" / "uninstall.sh").read_text(),
            )
        )
        for forbidden in (
            "curl ",
            "wget ",
            "npm ",
            "npx ",
            "pip ",
            "brew ",
            "git clone",
            "https://",
            "http://",
        ):
            self.assertNotIn(forbidden, combined)

    def test_dry_run_does_not_create_installation_or_call_claude(self) -> None:
        result = self._run_shell("install.sh", "--dry-run", *self._install_args())

        self.assertEqual(
            json.loads(result.stdout.splitlines()[-1])["status"], "success"
        )
        self.assertFalse(self.config_root.exists())
        self.assertFalse(self.data_root.exists())
        self.assertFalse(self.state_root.exists())
        self.assertFalse(self.fake_log.exists())

    def test_install_reinstall_and_uninstall_use_only_the_offline_marketplace(
        self,
    ) -> None:
        first = self._run_shell("install.sh", *self._install_args())
        second = self._run_shell("install.sh", *self._install_args())

        self.assertEqual(json.loads(first.stdout.splitlines()[-1])["status"], "success")
        self.assertEqual(
            json.loads(second.stdout.splitlines()[-1])["status"], "success"
        )
        rule_target = self.config_root / "rules" / "codegraph-harness.md"
        skill_target = self.codex_skill_root / "company-codegraph" / "SKILL.md"
        self.assertEqual(
            rule_target.read_bytes(),
            (self.bundle / "payload" / "rules" / "codegraph-harness.md").read_bytes(),
        )
        self.assertEqual(
            skill_target.read_bytes(),
            (
                self.bundle
                / "payload"
                / "codex"
                / "skills"
                / "company-codegraph"
                / "SKILL.md"
            ).read_bytes(),
        )
        receipt = self.state_root / "current"
        self.assertEqual(
            (receipt / "version").read_text(encoding="utf-8"), "0.1.0-test"
        )
        self.assertEqual(
            (receipt / "rule_target").read_text(encoding="utf-8"), str(rule_target)
        )

        uninstall = self._run_shell("uninstall.sh")
        self.assertEqual(
            json.loads(uninstall.stdout.splitlines()[-1])["status"], "success"
        )
        self.assertFalse(
            rule_target.exists(),
            f"uninstall stdout={uninstall.stdout!r}; stderr={uninstall.stderr!r}",
        )
        self.assertFalse(skill_target.exists())
        self.assertFalse(receipt.exists())
        calls = self.fake_log.read_text(encoding="utf-8").splitlines()
        self.assertEqual(
            calls,
            [
                f"plugin marketplace add {self.data_root}/versions/0.1.0-test/marketplace --scope user",
                "plugin install codegraph-evaluator@codegraph-harness --scope user --yes",
                f"plugin marketplace add {self.data_root}/versions/0.1.0-test/marketplace --scope user",
                "plugin install codegraph-evaluator@codegraph-harness --scope user --yes",
                "plugin uninstall codegraph-evaluator@codegraph-harness --scope user --yes",
                "plugin marketplace remove codegraph-harness --scope user",
            ],
        )
        self.assertFalse(self.fake_codex_log.exists())

    def test_runtime_installs_one_matching_pair_and_registers_both_clients(
        self,
    ) -> None:
        expected_gateway, expected_backend = self._use_runtime_bundle()

        result = self._run_shell("install.sh", *self._install_args())

        self.assertEqual(
            json.loads(result.stdout.splitlines()[-1])["status"], "success"
        )
        runtime_root = self.data_root / "runtime" / "macos-arm64"
        gateway = runtime_root / "bin" / "codegraph-gateway"
        backend = runtime_root / "bin" / "codebase-memory-mcp"
        self.assertEqual(gateway.read_bytes(), expected_gateway)
        self.assertEqual(backend.read_bytes(), expected_backend)
        self.assertFalse((self.data_root / "runtime" / "windows-x86_64").exists())
        receipt = self.state_root / "current"
        gateway_hash = hashlib.sha256(expected_gateway).hexdigest()
        backend_hash = hashlib.sha256(expected_backend).hexdigest()
        self.assertEqual((receipt / "gateway_sha256").read_text(), gateway_hash)
        self.assertEqual((receipt / "backend_sha256").read_text(), backend_hash)
        self.assertEqual((receipt / "claude_gateway_sha256").read_text(), gateway_hash)
        self.assertEqual((receipt / "codex_gateway_sha256").read_text(), gateway_hash)
        self.assertEqual((receipt / "claude_backend_sha256").read_text(), backend_hash)
        self.assertEqual((receipt / "codex_backend_sha256").read_text(), backend_hash)
        self.assertEqual((receipt / "runtime_platform").read_text(), "macos")
        self.assertEqual((receipt / "runtime_arch").read_text(), "arm64")

        claude_calls = self.fake_log.read_text(encoding="utf-8")
        codex_calls = self.fake_codex_log.read_text(encoding="utf-8")
        for calls in (claude_calls, codex_calls):
            self.assertIn("mcp add", calls)
            self.assertIn(str(gateway), calls)
            self.assertIn(str(backend), calls)
            self.assertIn(backend_hash, calls)
            self.assertIn(f"serve --allowed-root {self.allowed_root.resolve()}", calls)
            self.assertIn("--data-classification public-fixture", calls)
            self.assertNotIn("http://", calls)
            self.assertNotIn("https://", calls)

        second = self._run_shell("install.sh", *self._install_args())
        self.assertEqual(
            json.loads(second.stdout.splitlines()[-1])["status"], "success"
        )
        self.assertEqual(gateway.read_bytes(), expected_gateway)
        self.assertEqual(backend.read_bytes(), expected_backend)

        uninstall = self._run_shell("uninstall.sh")
        self.assertEqual(
            json.loads(uninstall.stdout.splitlines()[-1])["status"], "success"
        )
        self.assertFalse(runtime_root.exists())

    def test_runtime_requires_an_explicit_allowed_root(self) -> None:
        self._use_runtime_bundle()
        arguments = self._install_args()
        allowed_index = arguments.index("--allowed-root")
        del arguments[allowed_index : allowed_index + 2]

        result = self._run_shell("install.sh", *arguments, check=False)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("--allowed-root is required", result.stderr)
        self.assertFalse(self.data_root.exists())
        self.assertFalse(self.state_root.exists())

    def test_runtime_platform_mismatch_fails_before_creating_state(self) -> None:
        self._use_runtime_bundle()
        environment = self._environment()
        environment["CODEGRAPH_TEST_ARCH"] = "unsupported"
        result = subprocess.run(
            ["bash", str(self.bundle / "install.sh"), *self._install_args()],
            cwd=self.bundle,
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Unsupported architecture", result.stderr)
        self.assertFalse(self.data_root.exists())
        self.assertFalse(self.state_root.exists())

    def test_unselected_runtime_tampering_is_rejected(self) -> None:
        self._use_runtime_bundle()
        unselected = (
            self.bundle
            / "runtime"
            / "windows-x86_64"
            / "bin"
            / "codebase-memory-mcp.exe"
        )
        unselected.write_bytes(b"tampered")

        result = self._run_shell("install.sh", *self._install_args(), check=False)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Checksum mismatch", result.stderr)
        self.assertFalse(self.data_root.exists())

    def test_partial_failure_rolls_back_adapters_runtime_and_client_changes(
        self,
    ) -> None:
        self._use_runtime_bundle()
        environment = self._environment()
        environment["CODEGRAPH_FAKE_CLAUDE_FAIL_ON"] = "plugin install"
        result = subprocess.run(
            ["bash", str(self.bundle / "install.sh"), *self._install_args()],
            cwd=self.bundle,
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.config_root / "rules" / "codegraph-harness.md").exists())
        self.assertFalse(
            (self.codex_skill_root / "company-codegraph" / "SKILL.md").exists()
        )
        self.assertFalse((self.data_root / "runtime" / "macos-arm64").exists())
        self.assertFalse((self.state_root / "current").exists())

    def test_existing_mcp_registration_without_receipt_fails_safe(self) -> None:
        self._use_runtime_bundle()
        self.fake_cli_state.mkdir()
        (self.fake_cli_state / "claude-mcp").write_text("business registration\n")

        result = self._run_shell("install.sh", *self._install_args(), check=False)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("MCP registration already exists and is not owned", result.stderr)
        self.assertEqual(
            (self.fake_cli_state / "claude-mcp").read_text(),
            "business registration\n",
        )
        self.assertFalse(self.state_root.exists())

    def test_existing_codex_skill_without_receipt_fails_safe(self) -> None:
        target = self.codex_skill_root / "company-codegraph" / "SKILL.md"
        target.parent.mkdir(parents=True)
        target.write_text("business skill\n")

        result = self._run_shell("install.sh", *self._install_args(), check=False)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Codex skill target exists and is not owned", result.stderr)
        self.assertEqual(target.read_text(), "business skill\n")
        self.assertFalse(self.state_root.exists())

    def test_adapter_only_succeeds_without_client_executables(self) -> None:
        self._use_runtime_bundle()
        environment = self._environment()
        environment["PATH"] = "/usr/bin:/bin"
        result = subprocess.run(
            [
                "bash",
                str(self.bundle / "install.sh"),
                "--adapter-only",
                *self._install_args(),
            ],
            cwd=self.bundle,
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(
            (self.codex_skill_root / "company-codegraph" / "SKILL.md").is_file()
        )
        self.assertFalse(self.fake_log.exists())
        self.assertFalse(self.fake_codex_log.exists())

    def test_checksum_tampering_is_rejected_before_any_state_is_created(self) -> None:
        rule = self.bundle / "payload" / "rules" / "codegraph-harness.md"
        rule.write_text("tampered\n", encoding="utf-8")

        result = self._run_shell(
            "install.sh", "--dry-run", *self._install_args(), check=False
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Checksum mismatch", result.stderr)
        self.assertFalse(self.config_root.exists())
        self.assertFalse(self.data_root.exists())
        self.assertFalse(self.state_root.exists())
        self.assertFalse(self.fake_log.exists())

    def test_symlinked_bundle_file_is_rejected_before_installation(self) -> None:
        rule = self.bundle / "payload" / "rules" / "codegraph-harness.md"
        replacement = self.work / "same-content.md"
        replacement.write_bytes(rule.read_bytes())
        rule.unlink()
        rule.symlink_to(replacement)

        result = self._run_shell("install.sh", *self._install_args(), check=False)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("symlink", result.stderr)
        self.assertFalse(self.data_root.exists())

    def test_missing_mandatory_checksum_is_rejected(self) -> None:
        sums = self.bundle / "SHA256SUMS"
        lines = sums.read_text(encoding="utf-8").splitlines()
        sums.write_text(
            "\n".join(
                line for line in lines if not line.endswith("  bundle-manifest.json")
            )
            + "\n",
            encoding="utf-8",
        )

        result = self._run_shell(
            "install.sh", "--dry-run", *self._install_args(), check=False
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Mandatory file is not checksummed", result.stderr)
        self.assertFalse(self.config_root.exists())
        self.assertFalse(self.data_root.exists())
        self.assertFalse(self.state_root.exists())
        self.assertFalse(self.fake_log.exists())

    def test_unchecksummed_bundle_file_is_rejected_before_installation(self) -> None:
        injected = self.bundle / "payload" / "codex" / "injected-skill.md"
        injected.write_text("untrusted extension\n", encoding="utf-8")

        result = self._run_shell(
            "install.sh", "--dry-run", *self._install_args(), check=False
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Unchecksummed bundle file", result.stderr)
        self.assertFalse(self.config_root.exists())
        self.assertFalse(self.data_root.exists())
        self.assertFalse(self.state_root.exists())
        self.assertFalse(self.fake_log.exists())

    def test_symlinked_bundle_directory_is_rejected_before_installation(self) -> None:
        replacement = self.work / "untrusted-directory"
        replacement.mkdir()
        link = self.bundle / "payload" / "codex" / "untrusted-directory"
        link.symlink_to(replacement, target_is_directory=True)

        result = self._run_shell(
            "install.sh", "--dry-run", *self._install_args(), check=False
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("must not be a symlink", result.stderr)
        self.assertFalse(self.data_root.exists())

    def test_existing_rule_without_a_matching_receipt_is_never_overwritten(
        self,
    ) -> None:
        target = self.config_root / "rules" / "codegraph-harness.md"
        target.parent.mkdir(parents=True)
        target.write_text("business user rule\n", encoding="utf-8")

        result = self._run_shell(
            "install.sh", "--skip-plugin", *self._install_args(), check=False
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("not owned", result.stderr)
        self.assertEqual(target.read_text(encoding="utf-8"), "business user rule\n")
        self.assertFalse((self.state_root / "current").exists())

    def test_uninstall_preserves_a_rule_modified_after_installation(self) -> None:
        self._run_shell("install.sh", *self._install_args())
        target = self.config_root / "rules" / "codegraph-harness.md"
        target.write_text("business user amendment\n", encoding="utf-8")

        result = self._run_shell("uninstall.sh")

        self.assertEqual(
            json.loads(result.stdout.splitlines()[-1])["status"], "warning"
        )
        self.assertEqual(
            target.read_text(encoding="utf-8"), "business user amendment\n"
        )
        self.assertFalse((self.state_root / "current").exists())

    def test_uninstall_preserves_a_codex_skill_modified_after_installation(
        self,
    ) -> None:
        self._run_shell("install.sh", *self._install_args())
        target = self.codex_skill_root / "company-codegraph" / "SKILL.md"
        target.write_text("business user amendment\n", encoding="utf-8")

        result = self._run_shell("uninstall.sh")

        self.assertEqual(
            json.loads(result.stdout.splitlines()[-1])["status"], "warning"
        )
        self.assertEqual(
            target.read_text(encoding="utf-8"), "business user amendment\n"
        )
        self.assertFalse((self.state_root / "current").exists())

    def test_uninstall_preserves_a_modified_runtime(self) -> None:
        self._use_runtime_bundle()
        self._run_shell("install.sh", *self._install_args())
        runtime_root = self.data_root / "runtime" / "macos-arm64"
        gateway = runtime_root / "bin" / "codegraph-gateway"
        gateway.write_bytes(b"business amendment")

        result = self._run_shell("uninstall.sh")

        self.assertEqual(
            json.loads(result.stdout.splitlines()[-1])["status"], "warning"
        )
        self.assertEqual(gateway.read_bytes(), b"business amendment")
        self.assertFalse((self.state_root / "current").exists())

    def test_uninstall_preserves_runtime_for_user_modified_mcp_registration(
        self,
    ) -> None:
        self._use_runtime_bundle()
        self._run_shell("install.sh", *self._install_args())
        (self.fake_cli_state / "codex-mcp").write_text("business registration\n")
        runtime_root = self.data_root / "runtime" / "macos-arm64"

        result = self._run_shell("uninstall.sh")

        self.assertEqual(
            json.loads(result.stdout.splitlines()[-1])["status"], "warning"
        )
        self.assertTrue((self.fake_cli_state / "codex-mcp").is_file())
        self.assertTrue(runtime_root.is_dir())

    def test_uninstall_purges_graph_state_only_when_explicitly_requested(
        self,
    ) -> None:
        self._use_runtime_bundle()
        self._run_shell("install.sh", *self._install_args())
        graph_state = self.data_root / "graph-state" / "repository-id"
        graph_state.mkdir(parents=True)
        (graph_state / "index-manifest.json").write_text("derived graph\n")

        result = self._run_shell("uninstall.sh", "--purge-graph-state")

        self.assertEqual(
            json.loads(result.stdout.splitlines()[-1])["status"], "success"
        )
        self.assertFalse((self.data_root / "graph-state").exists())


class WindowsInstallerStaticTests(OfflineInstallerTestCase):
    def test_windows_scripts_have_integrity_ownership_and_rollback_guards(self) -> None:
        install = (PROJECT_ROOT / "installers" / "windows" / "install.ps1").read_text(
            encoding="utf-8"
        )
        uninstall = (
            PROJECT_ROOT / "installers" / "windows" / "uninstall.ps1"
        ).read_text(encoding="utf-8")

        for required in (
            '$ErrorActionPreference = "Stop"',
            "Get-FileHash",
            "Checksum mismatch",
            "Mandatory file is not checksummed",
            "$verifiedChecksums",
            "Get-ChildItem -LiteralPath $ScriptDir -Force -Recurse",
            "Unchecksummed bundle file",
            "Bundle entry must not be a reparse point",
            "Select-Object -First 1",
            "$gitCommand.Path",
            "[string]::IsNullOrWhiteSpace($serialized)",
            "Test-Path -LiteralPath",
            '"bundle-manifest.json"',
            "Unsafe checksum path",
            "Rule target exists and is not owned",
            "ruleInstalledSha256",
            "codexSkillInstalledSha256",
            "gatewaySha256",
            "backendSha256",
            "runtimePlatform",
            "runtimeArch",
            "claude plugin marketplace add",
            "claude plugin install",
            "claude mcp add",
            "codex mcp add",
            '"serve", "--allowed-root", $AllowedRoot',
            "--scope user",
            "catch {",
            "Remove-Item -LiteralPath $staging -Recurse -Force",
        ):
            self.assertIn(required, install)
        for required in (
            "ConvertFrom-Json",
            "ruleInstalledSha256",
            "codexSkillInstalledSha256",
            "gatewaySha256",
            "backendSha256",
            "Preserved user-modified Rule",
            "Preserved user-modified Codex skill",
            "claude plugin uninstall",
            "claude plugin marketplace remove",
            "claude mcp remove",
            "codex mcp remove",
            "Remove-Item -LiteralPath $receiptPath -Force",
            "PurgeGraphState",
        ):
            self.assertIn(required, uninstall)
        for unsafe in (
            "Invoke-Expression",
            "iex ",
            "DownloadString",
            "Invoke-WebRequest",
            "Start-BitsTransfer",
            "curl ",
            "wget ",
            "npm ",
            "npx ",
            "pip ",
        ):
            self.assertNotIn(unsafe, install)
            self.assertNotIn(unsafe, uninstall)

    @unittest.skipUnless(
        os.name == "nt" and shutil.which("pwsh"),
        "Windows pwsh is unavailable; static PowerShell contract is still tested",
    )
    def test_powershell_rejects_an_unchecksummed_bundle_file(self) -> None:
        injected = self.bundle / "payload" / "codex" / "injected-skill.md"
        injected.write_text("untrusted extension\n", encoding="utf-8")
        environment = self._environment()
        environment["CODEGRAPH_TEST_PLATFORM"] = "windows"
        environment["CODEGRAPH_TEST_ARCH"] = "x86_64"

        result = subprocess.run(
            [
                "pwsh",
                "-NoProfile",
                "-File",
                str(self.bundle / "install.ps1"),
                "-DryRun",
                "-ClaudeConfigDir",
                str(self.config_root),
                "-DataRoot",
                str(self.data_root),
                "-StateRoot",
                str(self.state_root),
                "-CodexSkillRoot",
                str(self.codex_skill_root),
                "-AllowedRoot",
                str(self.allowed_root),
            ],
            cwd=self.bundle,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Unchecksummed bundle file", result.stderr)
        self.assertFalse(self.data_root.exists())

    @unittest.skipUnless(
        os.name == "nt" and shutil.which("pwsh"),
        "Windows pwsh is unavailable; static PowerShell contract is still tested",
    )
    def test_powershell_installer_install_reinstall_and_uninstall(self) -> None:
        selected_gateway, selected_backend = self._use_runtime_bundle("windows-x86_64")
        install = self.bundle / "install.ps1"
        uninstall = self.bundle / "uninstall.ps1"
        prefix = ["pwsh", "-NoProfile", "-File"]
        environment = self._environment()
        environment["CODEGRAPH_TEST_PLATFORM"] = "windows"
        environment["CODEGRAPH_TEST_ARCH"] = "x86_64"
        arguments = [
            "-ClaudeConfigDir",
            str(self.config_root),
            "-DataRoot",
            str(self.data_root),
            "-StateRoot",
            str(self.state_root),
            "-CodexSkillRoot",
            str(self.codex_skill_root),
            "-AllowedRoot",
            str(self.allowed_root),
        ]

        for _ in range(2):
            result = subprocess.run(
                [*prefix, str(install), *arguments],
                cwd=self.bundle,
                env=environment,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(
                result.returncode,
                0,
                f"PowerShell install failed:\nstdout={result.stdout}\nstderr={result.stderr}",
            )
            self.assertIn('"status":"success"', result.stdout)
        rule_target = self.config_root / "rules" / "codegraph-harness.md"
        self.assertTrue(rule_target.is_file())
        runtime_root = self.data_root / "runtime" / "windows-x86_64" / "bin"
        self.assertEqual(
            (runtime_root / "codegraph-gateway.exe").read_bytes(), selected_gateway
        )
        self.assertEqual(
            (runtime_root / "codebase-memory-mcp.exe").read_bytes(), selected_backend
        )
        receipt = json.loads(
            (self.state_root / "current" / "receipt.json").read_text(
                encoding="utf-8-sig"
            )
        )
        self.assertTrue(receipt["runtimeInstalled"])
        self.assertEqual(receipt["runtimePlatform"], "windows")
        self.assertEqual(receipt["runtimeArch"], "x86_64")
        self.assertEqual(receipt["allowedRoot"], str(self.allowed_root))
        self.assertIn("--data-classification public-fixture", self.fake_log.read_text())
        self.assertIn(
            "--data-classification public-fixture", self.fake_codex_log.read_text()
        )

        result = subprocess.run(
            [
                *prefix,
                str(uninstall),
                "-DataRoot",
                str(self.data_root),
                "-StateRoot",
                str(self.state_root),
            ],
            cwd=self.bundle,
            env=environment,
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertIn('"status":"success"', result.stdout)
        self.assertFalse(rule_target.exists())
        self.assertFalse(runtime_root.exists())


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
