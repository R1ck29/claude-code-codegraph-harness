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
        self._write("clients/routing-policy.json", '{"tools":[]}\n')
        self._write("clients/render_adapters.py", "# renderer\n")
        self._write("codex/.codex-plugin/plugin.json", '{"name":"test"}\n')
        self._write("codex/skills/company-codegraph/SKILL.md", "# Company codegraph\n")
        self._write("codex/config.example.toml", "[mcp_servers.company_codegraph]\n")
        self._write("installers/macos/install.sh", "#!/bin/sh\n")
        self._write("installers/macos/uninstall.sh", "#!/bin/sh\n")
        self._write("installers/windows/install.ps1", "Write-Output ok\n")
        self._write("installers/windows/uninstall.ps1", "Write-Output ok\n")
        self._write("LICENSE", "Test license\n")
        self._write("THIRD_PARTY_NOTICES.md", "Test notice\n")
        self._write("README-INSTALL.txt", "Install instructions\n")
        self._write("docs/how-it-works-ja.md", "# 仕組み\r\n".encode("utf-8"))

    def _write(self, relative_path: str, content: str | bytes) -> Path:
        path = self.root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            path.write_bytes(content)
        else:
            path.write_text(content, encoding="utf-8")
        return path

    @staticmethod
    def _write_vendor(root: Path, relative_path: str, content: bytes) -> Path:
        path = root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return path

    @staticmethod
    def _runtime_matrix() -> list[dict[str, object]]:
        runtimes: list[dict[str, object]] = []
        for platform, arch, suffix in (
            ("macos", "arm64", ""),
            ("macos", "x86_64", ""),
            ("windows", "arm64", ".exe"),
            ("windows", "x86_64", ".exe"),
        ):
            runtime_id = f"{platform}-{arch}"
            runtimes.append(
                {
                    "platform": platform,
                    "arch": arch,
                    "files": [
                        {
                            "component": "gateway",
                            "source": f"{runtime_id}/gateway{suffix}",
                            "target": f"runtime/{runtime_id}/bin/codegraph-gateway{suffix}",
                            "sha256": "1" * 64,
                            "version": "1.0.0",
                            "commit": "1" * 40,
                            "license": "Apache-2.0",
                            "executable": True,
                        },
                        {
                            "component": "backend",
                            "source": f"{runtime_id}/cbm{suffix}",
                            "target": f"runtime/{runtime_id}/bin/codebase-memory-mcp{suffix}",
                            "sha256": "2" * 64,
                            "version": "0.10.8",
                            "commit": "2" * 40,
                            "license": "MIT",
                            "executable": True,
                        },
                    ],
                }
            )
        return runtimes

    def _profile(
        self,
        *,
        kind: str = "public",
        vendor_files: list[dict[str, str]] | None = None,
        runtimes: list[dict[str, object]] | None = None,
        approved_fixture_manifests: list[str] | None = None,
    ) -> Path:
        path = Path(self.temp_dir.name) / f"{kind}-profile.json"
        path.write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "profile_id": f"test-{kind}",
                    "kind": kind,
                    "description": "test profile",
                    "approved_fixture_manifests": (
                        approved_fixture_manifests
                        if approved_fixture_manifests is not None
                        else (["a" * 64] if kind == "internal" and runtimes else [])
                    ),
                    "vendor_files": vendor_files or [],
                    "runtimes": runtimes or [],
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
            self.assertIn("payload/clients/routing-policy.json", names)
            self.assertIn("payload/clients/render_adapters.py", names)
            self.assertIn("payload/codex/.codex-plugin/plugin.json", names)
            self.assertIn("payload/codex/skills/company-codegraph/SKILL.md", names)
            self.assertIn("payload/codex/config.example.toml", names)
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

    def test_bundle_includes_the_canonical_japanese_guide(self) -> None:
        output = Path(self.temp_dir.name) / "bundle.zip"

        build_bundle(self.root, output, version="1.0.0", profile_path=self._profile())

        with zipfile.ZipFile(output) as archive:
            self.assertIn("HOW-IT-WORKS-JA.md", archive.namelist())
            self.assertEqual(
                archive.read("HOW-IT-WORKS-JA.md"),
                (self.root / "docs" / "how-it-works-ja.md").read_bytes(),
            )

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

    def test_platform_runtime_is_deterministic_and_has_complete_metadata(self) -> None:
        vendor_dir = Path(self.temp_dir.name) / "vendor"
        vendor_dir.mkdir()
        runtimes: list[dict[str, object]] = []
        for platform, arch, executable_suffix in (
            ("macos", "arm64", ""),
            ("macos", "x86_64", ""),
            ("windows", "arm64", ".exe"),
            ("windows", "x86_64", ".exe"),
        ):
            runtime_id = f"{platform}-{arch}"
            gateway_bytes = (
                f"gateway {runtime_id} CODEGRAPH_APPROVED_FIXTURES:{'a' * 64}:END"
            ).encode()
            backend_bytes = f"backend {runtime_id}".encode()
            gateway_source = f"{runtime_id}/gateway{executable_suffix}"
            backend_source = f"{runtime_id}/cbm{executable_suffix}"
            self._write_vendor(vendor_dir, gateway_source, gateway_bytes)
            self._write_vendor(vendor_dir, backend_source, backend_bytes)
            runtimes.append(
                {
                    "platform": platform,
                    "arch": arch,
                    "files": [
                        {
                            "component": "gateway",
                            "source": gateway_source,
                            "target": f"runtime/{runtime_id}/bin/codegraph-gateway{executable_suffix}",
                            "sha256": _sha256(gateway_bytes),
                            "version": "1.0.0",
                            "commit": "1" * 40,
                            "license": "Apache-2.0",
                            "executable": True,
                        },
                        {
                            "component": "backend",
                            "source": backend_source,
                            "target": f"runtime/{runtime_id}/bin/codebase-memory-mcp{executable_suffix}",
                            "sha256": _sha256(backend_bytes),
                            "version": "0.10.8",
                            "commit": "2" * 40,
                            "license": "MIT",
                            "executable": True,
                        },
                    ],
                }
            )
        profile = self._profile(kind="internal", runtimes=runtimes)
        first = Path(self.temp_dir.name) / "runtime-one.zip"
        second = Path(self.temp_dir.name) / "runtime-two.zip"

        build_bundle(
            self.root,
            first,
            version="2.0.0",
            profile_path=profile,
            vendor_dir=vendor_dir,
        )
        build_bundle(
            self.root,
            second,
            version="2.0.0",
            profile_path=profile,
            vendor_dir=vendor_dir,
        )

        mismatched_profile = self._profile(
            kind="internal",
            runtimes=runtimes,
            approved_fixture_manifests=["b" * 64],
        )
        with self.assertRaisesRegex(BundleError, "compile-time fixture allowlist"):
            build_bundle(
                self.root,
                Path(self.temp_dir.name) / "mismatched-fixture.zip",
                version="2.0.0",
                profile_path=mismatched_profile,
                vendor_dir=vendor_dir,
            )

        self.assertEqual(first.read_bytes(), second.read_bytes())
        with zipfile.ZipFile(first) as archive:
            self.assertEqual(
                archive.read("runtime/macos-arm64/bin/codegraph-gateway"),
                (
                    f"gateway macos-arm64 CODEGRAPH_APPROVED_FIXTURES:{'a' * 64}:END"
                ).encode(),
            )
            self.assertEqual(
                archive.read("runtime/windows-x86_64/bin/codebase-memory-mcp.exe"),
                b"backend windows-x86_64",
            )
            runtime_manifest = json.loads(archive.read("runtime/manifest.json"))
            self.assertEqual(runtime_manifest["approved_fixture_manifests"], ["a" * 64])
            self.assertEqual(
                {
                    (item["platform"], item["arch"])
                    for item in runtime_manifest["runtimes"]
                },
                {
                    ("macos", "arm64"),
                    ("macos", "x86_64"),
                    ("windows", "arm64"),
                    ("windows", "x86_64"),
                },
            )
            for runtime in runtime_manifest["runtimes"]:
                self.assertEqual(
                    {entry["component"] for entry in runtime["files"]},
                    {"gateway", "backend"},
                )
                for entry in runtime["files"]:
                    self.assertNotIn("source", entry)
                    self.assertNotIn("download", entry)
                    self.assertRegex(entry["sha256"], r"^[0-9a-f]{64}$")
                    self.assertRegex(entry["commit"], r"^[0-9a-f]{40}$")
                    self.assertTrue(entry["version"])
                    self.assertTrue(entry["license"])
                    self.assertTrue(entry["executable"])
                    mode = archive.getinfo(entry["path"]).external_attr >> 16
                    self.assertEqual(mode & 0o111, 0o111)

            manifest = json.loads(archive.read("bundle-manifest.json"))
            self.assertEqual(
                {(item["platform"], item["arch"]) for item in manifest["runtimes"]},
                {
                    ("macos", "arm64"),
                    ("macos", "x86_64"),
                    ("windows", "arm64"),
                    ("windows", "x86_64"),
                },
            )

    def test_runtime_profile_requires_one_gateway_and_one_backend(self) -> None:
        vendor_dir = Path(self.temp_dir.name) / "vendor"
        vendor_dir.mkdir()
        (vendor_dir / "gateway").write_bytes(b"gateway")
        runtimes = self._runtime_matrix()
        runtimes[-1]["files"] = [runtimes[-1]["files"][0]]  # type: ignore[index]
        with self.assertRaisesRegex(BundleError, "gateway.*backend"):
            build_bundle(
                self.root,
                Path(self.temp_dir.name) / "bad-runtime.zip",
                version="1.0.0",
                profile_path=self._profile(kind="internal", runtimes=runtimes),
                vendor_dir=vendor_dir,
            )

    def test_runtime_profile_requires_a_compile_time_fixture_manifest(self) -> None:
        profile = self._profile(
            kind="internal",
            runtimes=self._runtime_matrix(),
            approved_fixture_manifests=[],
        )
        with self.assertRaisesRegex(BundleError, "approved fixture manifest"):
            build_bundle(
                self.root,
                Path(self.temp_dir.name) / "unsafe-runtime.zip",
                version="2.0.0",
                profile_path=profile,
                vendor_dir=Path(self.temp_dir.name) / "unused-vendor",
            )

    def test_public_profile_cannot_include_a_runtime(self) -> None:
        runtime: dict[str, object] = {
            "platform": "macos",
            "arch": "arm64",
            "files": [],
        }
        with self.assertRaisesRegex(BundleError, "public profile"):
            build_bundle(
                self.root,
                Path(self.temp_dir.name) / "bad-public-runtime.zip",
                version="1.0.0",
                profile_path=self._profile(runtimes=[runtime]),
            )

    def test_internal_runtime_profile_requires_the_complete_platform_matrix(
        self,
    ) -> None:
        with self.assertRaisesRegex(BundleError, "four OS/architecture"):
            build_bundle(
                self.root,
                Path(self.temp_dir.name) / "partial-matrix.zip",
                version="1.0.0",
                profile_path=self._profile(
                    kind="internal",
                    runtimes=[{"platform": "macos", "arch": "arm64", "files": []}],
                ),
            )

    def test_runtime_source_url_is_rejected(self) -> None:
        runtimes = self._runtime_matrix()
        runtimes[0]["files"][0]["source"] = "https://example.invalid/gateway"  # type: ignore[index]
        with self.assertRaisesRegex(BundleError, "relative path"):
            build_bundle(
                self.root,
                Path(self.temp_dir.name) / "url-runtime.zip",
                version="1.0.0",
                profile_path=self._profile(kind="internal", runtimes=runtimes),
            )

    def test_checked_in_runtime_template_is_offline_and_matches_backend_lock(
        self,
    ) -> None:
        project_root = Path(__file__).resolve().parents[1]
        template = json.loads(
            (
                project_root / "packaging" / "profiles" / "runtime-matrix.json.in"
            ).read_text(encoding="utf-8")
        )
        lock = json.loads(
            (project_root / "vendor" / "codebase-memory-v0.10.8.lock.json").read_text(
                encoding="utf-8"
            )
        )
        locked = {
            (
                "macos" if artifact["platform"] == "darwin" else "windows",
                (
                    "x86_64"
                    if artifact["architecture"] == "amd64"
                    else artifact["architecture"]
                ),
            ): artifact["executable_sha256"]
            for artifact in lock["artifacts"]
        }
        self.assertEqual(
            {(item["platform"], item["arch"]) for item in template["runtimes"]},
            set(locked),
        )
        serialized = json.dumps(template)
        self.assertNotIn("https://", serialized)
        self.assertNotIn("http://", serialized)
        for runtime in template["runtimes"]:
            backend = next(
                item for item in runtime["files"] if item["component"] == "backend"
            )
            self.assertEqual(
                backend["sha256"], locked[(runtime["platform"], runtime["arch"])]
            )
            self.assertEqual(backend["version"], lock["backend"]["version"])
            self.assertEqual(backend["commit"], lock["backend"]["commit"])
        self.assertEqual(
            {(entry["target"], entry["sha256"]) for entry in template["vendor_files"]},
            {
                (
                    "runtime/licenses/codebase-memory/LICENSE",
                    "1f58f9911dc5e3bcb96de28bb28e7b6bb7eb323952d29569c5d7214a152146bb",
                ),
                (
                    "runtime/licenses/codebase-memory/THIRD_PARTY_NOTICES.md",
                    "e7a63094936ada6ad063bea36b55495838b413c62e95137c1e0b798657ab8406",
                ),
                (
                    "runtime/licenses/codebase-memory/sbom.json",
                    lock["release"]["sbom"]["sha256"],
                ),
            },
        )

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
