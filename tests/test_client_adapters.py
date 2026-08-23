"""Contracts shared by the Claude Code and Codex client adapters."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = PROJECT_ROOT / "clients" / "routing-policy.json"
RENDERER_PATH = PROJECT_ROOT / "clients" / "render_adapters.py"
CLAUDE_SKILL_PATH = (
    PROJECT_ROOT
    / "plugins"
    / "codegraph-evaluator"
    / "skills"
    / "code-intelligence"
    / "SKILL.md"
)
CLAUDE_RULE_PATH = PROJECT_ROOT / "rules" / "codegraph-harness.md"
CODEX_ROOT = PROJECT_ROOT / "codex"
CODEX_SKILL_PATH = CODEX_ROOT / "skills" / "company-codegraph" / "SKILL.md"
CODEX_MANIFEST_PATH = CODEX_ROOT / ".codex-plugin" / "plugin.json"
CODEX_CONFIG_PATH = CODEX_ROOT / "config.example.toml"

EXPECTED_TOOLS = [
    "codegraph_status",
    "codegraph_search",
    "codegraph_neighbors",
    "codegraph_impact",
    "codegraph_architecture",
]
GENERATED_PATHS = [CLAUDE_SKILL_PATH, CLAUDE_RULE_PATH, CODEX_SKILL_PATH]


class ClientAdapterContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))

    def test_canonical_policy_exposes_only_the_five_read_only_tools(self) -> None:
        self.assertEqual(self.policy["schema_version"], 1)
        self.assertEqual(self.policy["policy_id"], "company-codegraph-routing")
        self.assertEqual(self.policy["tools"], EXPECTED_TOOLS)
        self.assertEqual(self.policy["model_action_scope"], "read-only")
        self.assertEqual(
            self.policy["fallback_conditions"],
            ["unavailable", "stale", "dirty", "truncated"],
        )
        self.assertEqual(self.policy["fallback_tools"], ["Read", "Grep", "LSP"])
        self.assertEqual(self.policy["truth_sources"], ["source", "tests"])
        self.assertEqual(
            self.policy["gateway_boundary"],
            {
                "transport": "registered local gateway only",
                "upstream_access": "never direct",
                "data_egress": "do not send source or graph output to another service",
            },
        )
        self.assertEqual(
            self.policy["freshness_strategy"],
            {
                "query_responses": "authoritative and revalidated on every call",
                "status_tool": "optional diagnostics only",
                "redundant_preflight": "do not call status before a normal query",
            },
        )

        serialized = json.dumps(self.policy, sort_keys=True).lower()
        for prohibited in (
            "codegraph_index",
            "codegraph_build",
            "codegraph_refresh",
            "codegraph_update",
            "codegraph_delete",
            "query_graph",
            "get_code_snippet",
        ):
            self.assertNotIn(prohibited, serialized)

    def test_generated_adapters_are_in_sync_with_canonical_policy(self) -> None:
        result = subprocess.run(
            [sys.executable, str(RENDERER_PATH), "--check"],
            cwd=PROJECT_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

        policy_hash = hashlib.sha256(POLICY_PATH.read_bytes()).hexdigest()
        marker = f"routing-policy-sha256: {policy_hash}"
        for path in GENERATED_PATHS:
            with self.subTest(path=path):
                self.assertIn(marker, path.read_text(encoding="utf-8"))

    def test_generated_adapters_share_routing_and_fallback_contract(self) -> None:
        for path in GENERATED_PATHS:
            text = path.read_text(encoding="utf-8")
            with self.subTest(path=path):
                for tool in EXPECTED_TOOLS:
                    self.assertIn(tool, text)
                for condition in ("stale", "dirty", "truncated"):
                    self.assertIn(condition, text)
                for fallback in ("Read", "Grep", "LSP"):
                    self.assertIn(fallback, text)
                self.assertIn("structural", text)
                self.assertIn("source and tests", text)
                self.assertIn("source-of-truth", text)
                self.assertIn("registered local gateway", text)
                self.assertIn("Do not send source or graph output", text)
                self.assertIn("Do not register or call an upstream", text)
                self.assertEqual(
                    set(re.findall(r"\bcodegraph_[a-z_]+\b", text)),
                    set(EXPECTED_TOOLS),
                )

                lowered = text.lower()
                for prohibited in (
                    "codegraph_index",
                    "codegraph_build",
                    "codegraph_refresh",
                    "codegraph_update",
                    "codegraph_delete",
                    "query_graph",
                    "get_code_snippet",
                ):
                    self.assertNotIn(prohibited, lowered)

    def test_codex_distribution_is_a_user_skill_and_valid_plugin(self) -> None:
        manifest = json.loads(CODEX_MANIFEST_PATH.read_text(encoding="utf-8"))
        claude_manifest = json.loads(
            (
                PROJECT_ROOT
                / "plugins"
                / "codegraph-evaluator"
                / ".claude-plugin"
                / "plugin.json"
            ).read_text(encoding="utf-8")
        )

        self.assertEqual(manifest["name"], "company-codegraph")
        self.assertEqual(manifest["version"], claude_manifest["version"])
        self.assertEqual(manifest["skills"], "./skills/")
        self.assertEqual(manifest["license"], "Apache-2.0")
        self.assertEqual(manifest["author"]["name"], "R1ck29")
        self.assertNotIn("mcpServers", manifest)
        self.assertFalse((CODEX_ROOT / "AGENTS.md").exists())

        text = CODEX_SKILL_PATH.read_text(encoding="utf-8")
        self.assertTrue(text.startswith("---\n"))
        self.assertIn("name: company-codegraph", text)
        self.assertIn("$HOME/.agents/skills/company-codegraph/SKILL.md", text)

    def test_codex_config_enforces_gateway_allowlist_and_read_only_approval(
        self,
    ) -> None:
        text = CODEX_CONFIG_PATH.read_text(encoding="utf-8")

        self.assertIn("[mcp_servers.company_codegraph]", text)
        self.assertIn('command = "__CODEGRAPH_GATEWAY_COMMAND__"', text)
        for required_argument in (
            '"serve"',
            '"--allowed-root", "__CODEGRAPH_ALLOWED_ROOT__"',
            '"--data-classification", "public-fixture"',
            '"--state-dir", "__CODEGRAPH_STATE_DIRECTORY__"',
            '"--cbm-binary", "__CODEGRAPH_BACKEND_COMMAND__"',
            '"--backend-sha256", "__CODEGRAPH_BACKEND_SHA256__"',
            '"--config", "__CODEGRAPH_CONFIG_FILE__"',
            '"--config-sha256", "__CODEGRAPH_CONFIG_SHA256__"',
            '"--git-binary", "__CODEGRAPH_GIT_COMMAND__"',
            '"--git-sha256", "__CODEGRAPH_GIT_SHA256__"',
        ):
            self.assertIn(required_argument, text)
        self.assertIn("required = true", text)
        self.assertIn('default_tools_approval_mode = "approve"', text)
        match = re.search(r"(?s)enabled_tools\s*=\s*(\[.*?\])", text)
        if match is None:
            self.fail("Codex config must declare enabled_tools")
        self.assertEqual(json.loads(match.group(1)), EXPECTED_TOOLS)
        self.assertNotIn("mcpServers", text)

        lowered = text.lower()
        for direct_backend_term in (
            "codebase-memory",
            "query_graph",
            "get_code_snippet",
        ):
            self.assertNotIn(direct_backend_term, lowered)

    def test_claude_manifest_remains_valid_and_describes_the_gateway(self) -> None:
        manifest_path = (
            PROJECT_ROOT
            / "plugins"
            / "codegraph-evaluator"
            / ".claude-plugin"
            / "plugin.json"
        )
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

        self.assertEqual(manifest["name"], "codegraph-evaluator")
        self.assertRegex(manifest["version"], r"^\d+\.\d+\.\d+")
        self.assertIn("local", manifest["description"].lower())
        self.assertIn("gateway", manifest["description"].lower())


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
