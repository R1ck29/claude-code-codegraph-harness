"""Offline installer regression tests.

The macOS entry point is exercised against a real ZIP and a fake ``claude``
command.  PowerShell gets the same execution path when ``pwsh`` is available;
otherwise static assertions still protect its integrity, verification, and
rollback contract on macOS CI runners.
"""

from __future__ import annotations

import json
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
        self.data_root = self.work / "data"
        self.state_root = self.work / "state"
        self.fake_log = self.work / "fake-claude.log"
        self.fake_bin = self.work / "bin"
        self.fake_bin.mkdir()
        self._make_fake_claude()

    def _make_fake_claude(self) -> None:
        if os.name == "nt":
            program = self.fake_bin / "claude.cmd"
            program.write_text(
                '@echo off\r\necho %*>> "%CODEGRAPH_FAKE_CLAUDE_LOG%"\r\nexit /b 0\r\n',
                encoding="utf-8",
            )
            return
        program = self.fake_bin / "claude"
        program.write_text(
            '#!/usr/bin/env bash\nset -eu\nprintf \'%s\\n\' "$*" >> "$CODEGRAPH_FAKE_CLAUDE_LOG"\n',
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
        ]


@unittest.skipIf(
    os.name == "nt",
    "macOS installer tests require a POSIX path environment",
)
class MacOSInstallerTests(OfflineInstallerTestCase):
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
        self.assertEqual(
            rule_target.read_bytes(),
            (self.bundle / "payload" / "rules" / "codegraph-harness.md").read_bytes(),
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
            "Test-Path -LiteralPath",
            '"bundle-manifest.json"',
            "Unsafe checksum path",
            "Rule target exists and is not owned",
            "ruleInstalledSha256",
            "claude plugin marketplace add",
            "claude plugin install",
            "--scope user",
            "catch {",
            "Remove-Item -LiteralPath $staging -Recurse -Force",
        ):
            self.assertIn(required, install)
        for required in (
            "ConvertFrom-Json",
            "ruleInstalledSha256",
            "Preserved user-modified Rule",
            "claude plugin uninstall",
            "claude plugin marketplace remove",
            "Remove-Item -LiteralPath $receiptPath -Force",
        ):
            self.assertIn(required, uninstall)
        for unsafe in (
            "Invoke-Expression",
            "iex ",
            "DownloadString",
            "Invoke-WebRequest",
        ):
            self.assertNotIn(unsafe, install)
            self.assertNotIn(unsafe, uninstall)

    @unittest.skipUnless(
        shutil.which("pwsh"),
        "pwsh is unavailable; static PowerShell contract is still tested",
    )
    def test_powershell_installer_install_reinstall_and_uninstall(self) -> None:
        install = self.bundle / "install.ps1"
        uninstall = self.bundle / "uninstall.ps1"
        prefix = ["pwsh", "-NoProfile", "-File"]
        arguments = [
            "-ClaudeConfigDir",
            str(self.config_root),
            "-DataRoot",
            str(self.data_root),
            "-StateRoot",
            str(self.state_root),
        ]

        for _ in range(2):
            result = subprocess.run(
                [*prefix, str(install), *arguments],
                cwd=self.bundle,
                env=self._environment(),
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
            env=self._environment(),
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertIn('"status":"success"', result.stdout)
        self.assertFalse(rule_target.exists())


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
