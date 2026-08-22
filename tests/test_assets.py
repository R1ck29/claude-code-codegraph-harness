"""Contract checks for files that Claude Code loads directly.

These checks deliberately avoid the Claude Code executable.  They catch bad
marketplace paths and malformed frontmatter before a bundle reaches an offline
user.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
import unittest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MARKETPLACE_PATH = PROJECT_ROOT / ".claude-plugin" / "marketplace.json"
PLUGIN_ROOT = PROJECT_ROOT / "plugins" / "codegraph-evaluator"


def _frontmatter(path: Path) -> dict[str, str]:
    """Read the small, scalar YAML frontmatter contract without PyYAML."""
    text = path.read_text(encoding="utf-8")
    parts = text.split("---", 2)
    if len(parts) != 3 or parts[0] != "":
        raise AssertionError(f"{path} must start with YAML frontmatter")
    values: dict[str, str] = {}
    for line in parts[1].strip().splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line.startswith((" ", "\t")):
            # Nested list values are checked by the caller that owns them.
            continue
        key, separator, value = line.partition(":")
        if not separator:
            raise AssertionError(f"invalid frontmatter line in {path}: {line!r}")
        values[key.strip()] = value.strip().strip('"')
    return values


class PluginAssetTests(unittest.TestCase):
    def test_marketplace_points_to_the_shipped_plugin_manifest(self) -> None:
        marketplace = json.loads(MARKETPLACE_PATH.read_text(encoding="utf-8"))

        self.assertEqual(marketplace["name"], "codegraph-harness")
        self.assertEqual(marketplace["owner"]["name"], "R1ck29")
        self.assertEqual(len(marketplace["plugins"]), 1)
        entry = marketplace["plugins"][0]
        self.assertEqual(entry["name"], "codegraph-evaluator")
        self.assertEqual(entry["source"], "./plugins/codegraph-evaluator")
        self.assertRegex(entry["version"], r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")

        source = (MARKETPLACE_PATH.parent.parent / entry["source"]).resolve()
        self.assertEqual(source, PLUGIN_ROOT.resolve())
        self.assertTrue((source / ".claude-plugin" / "plugin.json").is_file())

    def test_plugin_manifest_matches_marketplace_identity_and_public_metadata(
        self,
    ) -> None:
        marketplace = json.loads(MARKETPLACE_PATH.read_text(encoding="utf-8"))
        entry = marketplace["plugins"][0]
        manifest = json.loads(
            (PLUGIN_ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8")
        )

        self.assertEqual(manifest["name"], entry["name"])
        self.assertEqual(manifest["version"], entry["version"])
        self.assertEqual(manifest["license"], "Apache-2.0")
        self.assertEqual(manifest["author"]["name"], "R1ck29")
        for key in ("description", "homepage", "repository"):
            self.assertIsInstance(manifest[key], str)
            self.assertTrue(manifest[key].strip(), key)
        self.assertEqual(
            manifest["repository"],
            "https://github.com/R1ck29/claude-code-codegraph-harness",
        )
        project = (PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")
        project_version = re.search(r'(?m)^version = "([^"]+)"$', project)
        self.assertIsNotNone(project_version)
        self.assertEqual(manifest["version"], project_version.group(1))

    def test_skill_frontmatter_and_references_are_complete(self) -> None:
        skill = PLUGIN_ROOT / "skills" / "code-intelligence" / "SKILL.md"
        metadata = _frontmatter(skill)

        self.assertEqual(metadata["name"], "code-intelligence")
        self.assertTrue(metadata["description"])
        self.assertIn("argument-hint", metadata)
        skill_text = skill.read_text(encoding="utf-8")
        for reference in ("references/routing.md", "references/freshness.md"):
            self.assertTrue((skill.parent / reference).is_file(), reference)
            self.assertIn(reference, skill_text)

    def test_source_verifier_is_read_only_and_has_valid_frontmatter(self) -> None:
        agent = PLUGIN_ROOT / "agents" / "source-verifier.md"
        metadata = _frontmatter(agent)

        self.assertEqual(metadata["name"], "source-verifier")
        self.assertTrue(metadata["description"])
        self.assertEqual(metadata["maxTurns"], "12")
        text = agent.read_text(encoding="utf-8")
        self.assertRegex(text, r"(?m)^tools:\n(?:\s+- (?:Read|Grep|Glob)\n)+")
        self.assertNotRegex(text, r"(?im)^\s*-\s*(?:Write|Edit|Bash)\s*$")
        self.assertIn("Do not edit files", text)

    def test_rule_is_shipped_separately_and_enforces_evidence_boundaries(self) -> None:
        rule = PROJECT_ROOT / "rules" / "codegraph-harness.md"
        self.assertTrue(rule.is_file())
        text = rule.read_text(encoding="utf-8")
        self.assertIn("approved code-graph MCP", text)
        self.assertIn("source-of-truth", text)
        self.assertIn("current source and tests", text)
        self.assertIn("Do not claim token or quality improvements", text)
        self.assertNotIn("API_KEY", text)
        self.assertNotRegex(
            text, re.compile(r"(?i)ignore (?:previous|all) instructions")
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
