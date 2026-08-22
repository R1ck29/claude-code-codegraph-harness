from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from codegraph_harness.bundle import BundleError, build_bundle, run_bundle_cli


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class BundleBuilderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name) / "repo"
        self.root.mkdir()
        self._write(".claude-plugin/marketplace.json", '{"name":"test"}\n')
        self._write("plugins/evaluator/plugin.json", "{}\n")
        self._write("rules/codegraph-harness.md", "# Company rule\n")
        self._write("installers/macos/install.sh", "#!/bin/sh\n")
        self._write("installers/macos/uninstall.sh", "#!/bin/sh\n")
        self._write("installers/windows/install.ps1", "Write-Output ok\n")
        self._write("installers/windows/uninstall.ps1", "Write-Output ok\n")
        self._write("LICENSE", "Test license\n")
        self._write("THIRD_PARTY_NOTICES.md", "Test notice\n")
        self._write("README-INSTALL.txt", "Install instructions\n")

    def _write(self, relative_path: str, content: str | bytes) -> Path:
        path = self.root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            path.write_bytes(content)
        else:
            path.write_text(content, encoding="utf-8")
        return path

    def _profile(
        self,
        *,
        kind: str = "public",
        vendor_files: list[dict[str, str]] | None = None,
    ) -> Path:
        path = Path(self.temp_dir.name) / f"{kind}-profile.json"
        path.write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "profile_id": f"test-{kind}",
                    "kind": kind,
                    "description": "test profile",
                    "vendor_files": vendor_files or [],
                }
            ),
            encoding="utf-8",
        )
        return path

    def test_public_bundle_is_deterministic_and_has_contract_files(self) -> None:
        profile = self._profile()
        output_one = Path(self.temp_dir.name) / "one.zip"
        output_two = Path(self.temp_dir.name) / "two.zip"

        response_one = build_bundle(
            self.root, output_one, version="1.2.3", profile_path=profile
        )
        response_two = build_bundle(
            self.root, output_two, version="1.2.3", profile_path=profile
        )

        self.assertEqual(output_one.read_bytes(), output_two.read_bytes())
        self.assertEqual(response_one["status"], "success")
        self.assertTrue(response_one["summary"])
        self.assertIsInstance(response_one["next_actions"], list)
        self.assertIsInstance(response_one["artifacts"], list)

        with zipfile.ZipFile(output_one) as archive:
            names = archive.namelist()
            self.assertEqual(names, sorted(names))
            self.assertIn("VERSION", names)
            self.assertIn("profile.json", names)
            self.assertIn("SHA256SUMS", names)
            self.assertIn("bundle-manifest.json", names)
            self.assertIn("install.sh", names)
            self.assertIn("uninstall.sh", names)
            self.assertIn("install.ps1", names)
            self.assertIn("uninstall.ps1", names)
            self.assertIn("payload/marketplace/.claude-plugin/marketplace.json", names)
            self.assertIn("payload/marketplace/plugins/evaluator/plugin.json", names)
            self.assertIn("payload/rules/codegraph-harness.md", names)
            self.assertIn("THIRD_PARTY_NOTICES.md", names)
            self.assertIn("README-INSTALL.txt", names)
            self.assertNotIn("installers/macos/install.sh", names)
            self.assertEqual(archive.read("VERSION"), b"1.2.3\n")
            install_mode = archive.getinfo("install.sh").external_attr >> 16
            self.assertEqual(install_mode & 0o777, 0o755)

            manifest = json.loads(archive.read("bundle-manifest.json"))
            self.assertEqual(manifest["status"], "success")
            self.assertEqual(manifest["version"], "1.2.3")
            self.assertEqual(manifest["profile"]["kind"], "public")
            self.assertTrue(manifest["summary"])
            self.assertIsInstance(manifest["next_actions"], list)
            self.assertIsInstance(manifest["artifacts"], list)

            sums = archive.read("SHA256SUMS").decode("utf-8").splitlines()
            expected_hashed_names = set(names) - {"SHA256SUMS"}
            actual_hashed_names = {line.split("  ", 1)[1] for line in sums}
            self.assertEqual(actual_hashed_names, expected_hashed_names)
            for line in sums:
                digest, name = line.split("  ", 1)
                self.assertEqual(digest, _sha256(archive.read(name)))

    def test_default_exclusions_omit_metadata_cache_results_secrets_and_binaries(
        self,
    ) -> None:
        self._write("plugins/evaluator/.git/config", "secret")
        self._write("plugins/evaluator/__pycache__/module.pyc", b"bytecode")
        self._write("plugins/evaluator/results/report.json", "{}")
        self._write("plugins/evaluator/private.pem", "private")
        self._write("plugins/evaluator/.env.production", "TOKEN=secret")
        self._write("plugins/evaluator/vendor.exe", b"binary")
        self._write("plugins/evaluator/vendor-tool", b"\x7fELFbinary")
        self._write("installers/windows/vendor.exe", b"binary")

        output = Path(self.temp_dir.name) / "bundle.zip"
        build_bundle(self.root, output, version="1.0.0", profile_path=self._profile())

        with zipfile.ZipFile(output) as archive:
            names = archive.namelist()
        self.assertNotIn("payload/marketplace/plugins/evaluator/.git/config", names)
        self.assertNotIn(
            "payload/marketplace/plugins/evaluator/__pycache__/module.pyc", names
        )
        self.assertNotIn(
            "payload/marketplace/plugins/evaluator/results/report.json", names
        )
        self.assertNotIn("payload/marketplace/plugins/evaluator/private.pem", names)
        self.assertNotIn("payload/marketplace/plugins/evaluator/.env.production", names)
        self.assertNotIn("payload/marketplace/plugins/evaluator/vendor.exe", names)
        self.assertNotIn("payload/marketplace/plugins/evaluator/vendor-tool", names)
        self.assertNotIn("installers/windows/vendor.exe", names)

    def test_internal_profile_injects_only_enumerated_verified_vendor_files(
        self,
    ) -> None:
        vendor_dir = Path(self.temp_dir.name) / "vendor"
        vendor_dir.mkdir()
        allowed = vendor_dir / "bin" / "tool.exe"
        allowed.parent.mkdir()
        allowed.write_bytes(b"verified binary")
        (vendor_dir / "not-listed.exe").write_bytes(b"must not be included")
        profile = self._profile(
            kind="internal",
            vendor_files=[
                {
                    "source": "bin/tool.exe",
                    "target": "vendor/windows/tool.exe",
                    "sha256": _sha256(b"verified binary"),
                }
            ],
        )
        output = Path(self.temp_dir.name) / "internal.zip"

        build_bundle(
            self.root,
            output,
            version="2.0.0",
            profile_path=profile,
            vendor_dir=vendor_dir,
        )

        with zipfile.ZipFile(output) as archive:
            self.assertEqual(
                archive.read("vendor/windows/tool.exe"), b"verified binary"
            )
            self.assertNotIn("not-listed.exe", archive.namelist())

    def test_public_profile_cannot_inject_vendor_files(self) -> None:
        profile = self._profile(
            vendor_files=[
                {
                    "source": "tool.exe",
                    "target": "vendor/tool.exe",
                    "sha256": "0" * 64,
                }
            ]
        )
        with self.assertRaisesRegex(BundleError, "public profile"):
            build_bundle(
                self.root,
                Path(self.temp_dir.name) / "bad.zip",
                version="1.0.0",
                profile_path=profile,
                vendor_dir=Path(self.temp_dir.name),
            )

    def test_internal_vendor_files_require_vendor_dir(self) -> None:
        profile = self._profile(
            kind="internal",
            vendor_files=[
                {
                    "source": "tool.exe",
                    "target": "vendor/tool.exe",
                    "sha256": "0" * 64,
                }
            ],
        )
        with self.assertRaisesRegex(BundleError, "vendor_dir"):
            build_bundle(
                self.root,
                Path(self.temp_dir.name) / "bad.zip",
                version="1.0.0",
                profile_path=profile,
            )

    def test_vendor_source_path_traversal_is_rejected(self) -> None:
        self._assert_vendor_entry_rejected(
            {
                "source": "../escape.exe",
                "target": "vendor/tool.exe",
                "sha256": "0" * 64,
            },
            "relative path",
        )

    def test_vendor_target_path_traversal_is_rejected(self) -> None:
        self._assert_vendor_entry_rejected(
            {"source": "tool.exe", "target": "../escape.exe", "sha256": "0" * 64},
            "relative path",
        )

    def test_vendor_absolute_path_is_rejected(self) -> None:
        self._assert_vendor_entry_rejected(
            {
                "source": "/tmp/tool.exe",
                "target": "vendor/tool.exe",
                "sha256": "0" * 64,
            },
            "relative path",
        )

    @unittest.skipIf(os.name == "nt", "symlink creation may require Windows privileges")
    def test_vendor_symlink_is_rejected(self) -> None:
        outside = Path(self.temp_dir.name) / "outside.exe"
        outside.write_bytes(b"outside")
        vendor_dir = Path(self.temp_dir.name) / "vendor"
        vendor_dir.mkdir()
        (vendor_dir / "tool.exe").symlink_to(outside)
        profile = self._profile(
            kind="internal",
            vendor_files=[
                {
                    "source": "tool.exe",
                    "target": "vendor/tool.exe",
                    "sha256": _sha256(b"outside"),
                }
            ],
        )
        with self.assertRaisesRegex(BundleError, "symlink"):
            build_bundle(
                self.root,
                Path(self.temp_dir.name) / "bad.zip",
                version="1.0.0",
                profile_path=profile,
                vendor_dir=vendor_dir,
            )

    def test_vendor_hash_mismatch_is_rejected(self) -> None:
        vendor_dir = Path(self.temp_dir.name) / "vendor"
        vendor_dir.mkdir()
        (vendor_dir / "tool.exe").write_bytes(b"actual")
        profile = self._profile(
            kind="internal",
            vendor_files=[
                {
                    "source": "tool.exe",
                    "target": "vendor/tool.exe",
                    "sha256": _sha256(b"expected"),
                }
            ],
        )
        with self.assertRaisesRegex(BundleError, "hash mismatch"):
            build_bundle(
                self.root,
                Path(self.temp_dir.name) / "bad.zip",
                version="1.0.0",
                profile_path=profile,
                vendor_dir=vendor_dir,
            )

    def test_duplicate_vendor_target_is_rejected(self) -> None:
        vendor_dir = Path(self.temp_dir.name) / "vendor"
        vendor_dir.mkdir()
        (vendor_dir / "one").write_bytes(b"one")
        (vendor_dir / "two").write_bytes(b"two")
        profile = self._profile(
            kind="internal",
            vendor_files=[
                {
                    "source": "one",
                    "target": "vendor/tool",
                    "sha256": _sha256(b"one"),
                },
                {
                    "source": "two",
                    "target": "vendor/tool",
                    "sha256": _sha256(b"two"),
                },
            ],
        )
        with self.assertRaisesRegex(BundleError, "duplicate target"):
            build_bundle(
                self.root,
                Path(self.temp_dir.name) / "bad.zip",
                version="1.0.0",
                profile_path=profile,
                vendor_dir=vendor_dir,
            )

    def test_vendor_target_cannot_replace_repository_file(self) -> None:
        vendor_dir = Path(self.temp_dir.name) / "vendor"
        vendor_dir.mkdir()
        (vendor_dir / "tool").write_bytes(b"replacement")
        profile = self._profile(
            kind="internal",
            vendor_files=[
                {
                    "source": "tool",
                    "target": "LICENSE",
                    "sha256": _sha256(b"replacement"),
                }
            ],
        )
        with self.assertRaisesRegex(BundleError, "duplicate target"):
            build_bundle(
                self.root,
                Path(self.temp_dir.name) / "bad.zip",
                version="1.0.0",
                profile_path=profile,
                vendor_dir=vendor_dir,
            )

    @unittest.skipIf(os.name == "nt", "symlink creation may require Windows privileges")
    def test_repository_symlink_is_rejected(self) -> None:
        outside = Path(self.temp_dir.name) / "outside.md"
        outside.write_text("outside", encoding="utf-8")
        (self.root / "rules" / "linked.md").symlink_to(outside)
        with self.assertRaisesRegex(BundleError, "symlink"):
            build_bundle(
                self.root,
                Path(self.temp_dir.name) / "bad.zip",
                version="1.0.0",
                profile_path=self._profile(),
            )

    def test_every_bundle_target_must_be_portable_to_windows(self) -> None:
        unsafe_targets = (
            "payload/marketplace/plugins/evaluator/x\\..\\LICENSE",
            "payload/marketplace/plugins/evaluator/x:y",
            "payload/marketplace/plugins/evaluator/CON.txt",
            "payload/marketplace/plugins/evaluator/trailing.",
            "payload/marketplace/plugins/evaluator/trailing ",
            "payload/marketplace/plugins/evaluator/../LICENSE",
        )
        for unsafe_target in unsafe_targets:
            with self.subTest(target=unsafe_target):
                with patch(
                    "codegraph_harness.bundle._iter_repository_files",
                    return_value=iter(((unsafe_target, b"unsafe"),)),
                ):
                    with self.assertRaisesRegex(BundleError, "portable|normalized"):
                        build_bundle(
                            self.root,
                            Path(self.temp_dir.name) / "bad.zip",
                            version="1.0.0",
                            profile_path=self._profile(),
                        )

    def test_cli_returns_zero_and_prints_response_contract(self) -> None:
        output = Path(self.temp_dir.name) / "cli.zip"
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            result = run_bundle_cli(
                [
                    "build",
                    "--repo-root",
                    str(self.root),
                    "--output",
                    str(output),
                    "--version",
                    "3.0.0",
                    "--profile",
                    str(self._profile()),
                ]
            )
        self.assertEqual(result, 0)
        self.assertTrue(output.is_file())
        response = json.loads(stdout.getvalue())
        self.assertEqual(response["status"], "success")
        self.assertEqual(response["artifacts"][0]["path"], str(output.resolve()))

    def test_cli_help_returns_zero(self) -> None:
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            result = run_bundle_cli(["--help"])
        self.assertEqual(result, 0)
        self.assertIn("--vendor-dir", stdout.getvalue())

    def _assert_vendor_entry_rejected(
        self, entry: dict[str, str], message: str
    ) -> None:
        vendor_dir = Path(self.temp_dir.name) / "vendor"
        vendor_dir.mkdir()
        (vendor_dir / "tool.exe").write_bytes(b"tool")
        with self.assertRaisesRegex(BundleError, message):
            build_bundle(
                self.root,
                Path(self.temp_dir.name) / "bad.zip",
                version="1.0.0",
                profile_path=self._profile(kind="internal", vendor_files=[entry]),
                vendor_dir=vendor_dir,
            )


if __name__ == "__main__":
    unittest.main()
