from __future__ import annotations

import json
from pathlib import Path
import re
import unittest

try:
    import jsonschema
except ImportError:  # Optional contract-validation dependency.
    jsonschema = None


ROOT = Path(__file__).resolve().parents[1]


class ReleaseMetadataTests(unittest.TestCase):
    def test_release_versions_are_consistent(self) -> None:
        expected = "0.2.0-rc.1"
        pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        package = (ROOT / "src" / "codegraph_harness" / "__init__.py").read_text(
            encoding="utf-8"
        )
        gateway = (ROOT / "gateway" / "internal" / "gateway" / "types.go").read_text(
            encoding="utf-8"
        )
        manifests = (
            ROOT / "plugins" / "codegraph-evaluator" / ".claude-plugin" / "plugin.json",
            ROOT / "codex" / ".codex-plugin" / "plugin.json",
        )
        marketplace = json.loads(
            (ROOT / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8")
        )

        self.assertRegex(pyproject, rf'(?m)^version = "{re.escape(expected)}"$')
        self.assertIn(f'__version__ = "{expected}"', package)
        self.assertIn(f'Version               = "{expected}"', gateway)
        for manifest_path in manifests:
            self.assertEqual(
                json.loads(manifest_path.read_text(encoding="utf-8"))["version"],
                expected,
            )
        self.assertEqual(marketplace["plugins"][0]["version"], expected)


@unittest.skipIf(jsonschema is None, "jsonschema is not installed")
class ProductContractTests(unittest.TestCase):
    def test_backend_acceptance_evidence_matches_schema(self) -> None:
        schema = json.loads(
            (ROOT / "security" / "backend-acceptance.schema.json").read_text(
                encoding="utf-8"
            )
        )
        evidence = json.loads(
            (
                ROOT / "security" / "acceptance" / "cbm-v0.10.8-macos-arm64.json"
            ).read_text(encoding="utf-8")
        )

        jsonschema.Draft202012Validator(schema).validate(evidence)
        self.assertEqual(evidence["decision"], "public-fixture-only")

    def test_vendor_lock_contains_exactly_four_unique_platforms(self) -> None:
        lock = json.loads(
            (ROOT / "vendor" / "codebase-memory-v0.10.8.lock.json").read_text(
                encoding="utf-8"
            )
        )

        platforms = {
            (artifact["platform"], artifact["architecture"])
            for artifact in lock["artifacts"]
        }
        self.assertEqual(
            platforms,
            {
                ("darwin", "arm64"),
                ("darwin", "amd64"),
                ("windows", "arm64"),
                ("windows", "amd64"),
            },
        )
        self.assertEqual(len(lock["artifacts"]), 4)
        for artifact in lock["artifacts"]:
            self.assertRegex(artifact["archive_sha256"], r"^[0-9a-f]{64}$")
            self.assertRegex(artifact["executable_sha256"], r"^[0-9a-f]{64}$")

    def test_gateway_result_schema_rejects_absolute_paths(self) -> None:
        schema = json.loads(
            (ROOT / "contracts" / "gateway-result.schema.json").read_text(
                encoding="utf-8"
            )
        )
        result = {
            "status": "success",
            "summary": "one definition",
            "freshness": {
                "usable": True,
                "reason": "fresh",
                "generation": "generation-0001",
            },
            "results": [
                {
                    "symbol_id": "python:function:run",
                    "name": "run",
                    "kind": "function",
                    "path": "src/example.py",
                    "line_start": 10,
                    "line_end": 12,
                    "relation": "definition",
                    "evidence": "parser",
                }
            ],
            "page": {"returned": 1, "truncated": False, "next_cursor": None},
            "next_actions": [],
        }
        validator = jsonschema.Draft202012Validator(schema)

        validator.validate(result)
        result["results"][0]["path"] = "/private/source.py"
        with self.assertRaises(jsonschema.ValidationError):
            validator.validate(result)


if __name__ == "__main__":
    unittest.main()
