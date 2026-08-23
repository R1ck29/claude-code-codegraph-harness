from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from codegraph_harness.bundle import build_bundle

PROJECT_ROOT = Path(__file__).resolve().parents[1]
GUIDE_PATH = PROJECT_ROOT / "docs" / "how-it-works-ja.md"
CLAUDE_EVIDENCE_PATH = (
    PROJECT_ROOT / "docs" / "evidence" / "claude-v0.2.0-public-token-eval.md"
)


class DocumentationTests(unittest.TestCase):
    def test_japanese_guide_is_linked_from_repository_and_offline_bundle(self) -> None:
        self.assertTrue(GUIDE_PATH.is_file())
        self.assertTrue(GUIDE_PATH.read_text(encoding="utf-8").strip())

        readme = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("docs/how-it-works-ja.md", readme)

        install_guide = (PROJECT_ROOT / "README-INSTALL.txt").read_text(
            encoding="utf-8"
        )
        self.assertIn("HOW-IT-WORKS-JA.md", install_guide)

    def test_real_bundle_records_the_canonical_guide(self) -> None:
        guide = GUIDE_PATH.read_bytes()
        guide_sha256 = hashlib.sha256(guide).hexdigest()
        with tempfile.TemporaryDirectory() as temporary_directory:
            output = Path(temporary_directory) / "bundle.zip"
            build_bundle(
                PROJECT_ROOT,
                output,
                version="0.1.1-documentation-test",
                profile_path=PROJECT_ROOT / "packaging" / "profiles" / "public.json",
            )

            with zipfile.ZipFile(output) as archive:
                self.assertEqual(archive.read("HOW-IT-WORKS-JA.md"), guide)
                manifest = json.loads(archive.read("bundle-manifest.json"))
                guide_artifact = next(
                    artifact
                    for artifact in manifest["artifacts"]
                    if artifact["path"] == "HOW-IT-WORKS-JA.md"
                )
                self.assertEqual(guide_artifact["sha256"], guide_sha256)
                self.assertEqual(guide_artifact["size"], len(guide))
                self.assertEqual(guide_artifact["source"], "repository")

                checksum_entries = {
                    name: digest
                    for digest, name in (
                        line.split("  ", 1)
                        for line in archive.read("SHA256SUMS")
                        .decode("utf-8")
                        .splitlines()
                    )
                }
                self.assertEqual(checksum_entries["HOW-IT-WORKS-JA.md"], guide_sha256)

    def test_claude_evidence_is_linked_and_preserves_the_failed_cost_gate(self) -> None:
        evidence = CLAUDE_EVIDENCE_PATH.read_text(encoding="utf-8")
        readme = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")
        guide = GUIDE_PATH.read_text(encoding="utf-8")

        self.assertIn("claude-v0.2.0-public-token-eval.md", readme)
        self.assertIn("claude-v0.2.0-public-token-eval.md", guide)
        self.assertIn("111.61%", evidence)
        self.assertIn("57.56%", evidence)
        self.assertIn("does not authorize company-source use", evidence)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
