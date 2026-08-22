"""Static regression checks for the public no-egress boundary.

These tests prove only that repository-owned Python and installer code contains
no network client. They do not prove that configured Claude Code or backend
subprocesses are isolated; SECURITY.md defines the required runtime evidence.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
import unittest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = PROJECT_ROOT / "src" / "codegraph_harness"
INSTALLERS = (
    PROJECT_ROOT / "installers" / "macos" / "install.sh",
    PROJECT_ROOT / "installers" / "macos" / "uninstall.sh",
    PROJECT_ROOT / "installers" / "windows" / "install.ps1",
    PROJECT_ROOT / "installers" / "windows" / "uninstall.ps1",
)
NETWORK_MODULES = {
    "aiohttp",
    "ftplib",
    "http",
    "httpx",
    "requests",
    "socket",
    "urllib",
}


class NoEgressStaticTests(unittest.TestCase):
    def test_python_package_has_no_network_client_import(self) -> None:
        findings: list[str] = []
        for path in SOURCE_ROOT.glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                names: list[str] = []
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module:
                    names = [node.module]
                for name in names:
                    if name.split(".", 1)[0] in NETWORK_MODULES:
                        findings.append(f"{path.name}:{node.lineno}:{name}")
        self.assertEqual(findings, [])

    def test_installers_have_no_download_primitive(self) -> None:
        forbidden = (
            "curl ",
            "wget ",
            "Invoke-WebRequest",
            "Invoke-RestMethod",
            "DownloadFile",
            "DownloadString",
            "Start-BitsTransfer",
        )
        for path in INSTALLERS:
            text = path.read_text(encoding="utf-8")
            for primitive in forbidden:
                self.assertNotIn(primitive, text, f"{primitive!r} in {path}")

    def test_public_plugin_does_not_ship_an_mcp_server(self) -> None:
        plugin_root = PROJECT_ROOT / "plugins" / "codegraph-evaluator"
        self.assertFalse((plugin_root / ".mcp.json").exists())
        self.assertFalse((plugin_root / "mcp.json").exists())

    def test_rejected_graphify_conditions_are_public_fixture_only(self) -> None:
        registry = json.loads(
            (PROJECT_ROOT / "candidates" / "registry.json").read_text(encoding="utf-8")
        )
        graphify = next(
            item for item in registry["candidates"] if item["id"] == "graphify"
        )
        self.assertEqual(graphify["decision"], "rejected-for-company-source")
        self.assertEqual(graphify["allowed_data_classifications"], ["public-fixture"])

        conditions = json.loads(
            (
                PROJECT_ROOT / "evaluation" / "configs" / "conditions.example.json"
            ).read_text(encoding="utf-8")
        )["conditions"]
        graphify_conditions = [
            item for item in conditions if item["id"].startswith("graphify-")
        ]
        self.assertEqual(len(graphify_conditions), 2)
        for condition in graphify_conditions:
            self.assertEqual(
                condition["allowed_data_classifications"], ["public-fixture"]
            )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
