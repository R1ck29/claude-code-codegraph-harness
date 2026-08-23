from __future__ import annotations

from contextlib import redirect_stdout
import hashlib
import io
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch

try:
    import jsonschema
except ImportError:  # Optional contract-validation dependency.
    jsonschema = None

from codegraph_harness.evaluation import (
    EvaluationConfigError,
    normalize_claude_output,
    normalize_codex_output,
    render_command,
    run_evaluation,
    run_evaluation_cli,
)


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def _claude_command() -> list[str]:
    script = (
        "import json,sys; "
        "prompt=sys.stdin.read(); "
        "print(json.dumps({'type':'result','usage':"
        "{'input_tokens':11,'output_tokens':7},'total_cost_usd':0.125})); "
        "sys.exit(9 if prompt == 'fail-secret' else 0)"
    )
    return [sys.executable, "-c", script]


def _codex_command(*, graph: bool) -> list[str]:
    command = [
        "codex",
        "exec",
        "--json",
        "--ephemeral",
        "--ignore-user-config",
        "--strict-config",
        "--sandbox",
        "read-only",
        "-C",
        "{repo}",
    ]
    if graph:
        command.extend(
            [
                "-c",
                'mcp_servers.company_codegraph.command="/managed/codegraph-gateway"',
                "-c",
                'mcp_servers.company_codegraph.args=["serve"]',
                "-c",
                "mcp_servers.company_codegraph.enabled_tools="
                '["codegraph_status","codegraph_search","codegraph_neighbors",'
                '"codegraph_impact","codegraph_architecture"]',
                "-c",
                "mcp_servers.company_codegraph.required=true",
                "-c",
                'mcp_servers.company_codegraph.default_tools_approval_mode="approve"',
            ]
        )
    command.append("-")
    return command


class RenderingTests(unittest.TestCase):
    def test_only_documented_placeholders_are_accepted(self) -> None:
        rendered = render_command(
            [
                "tool",
                "--repo",
                "{repo}",
                "--state={state}",
                "--harness",
                "{harness}",
                "{prompt}",
            ],
            {
                "repo": "/r",
                "state": "/s",
                "prompt": "hello",
                "harness": "/h",
            },
        )
        self.assertEqual(
            rendered,
            [
                "tool",
                "--repo",
                "/r",
                "--state=/s",
                "--harness",
                "/h",
                "hello",
            ],
        )

        with self.assertRaises(EvaluationConfigError):
            render_command(
                ["tool", "{seed}"],
                {
                    "repo": "/r",
                    "state": "/s",
                    "prompt": "hello",
                    "harness": "/h",
                },
            )

        with self.assertRaises(EvaluationConfigError):
            render_command(
                "tool {prompt}",  # type: ignore[arg-type]
                {
                    "repo": "/r",
                    "state": "/s",
                    "prompt": "hello",
                    "harness": "/h",
                },
            )


class ClaudeOutputTests(unittest.TestCase):
    def test_normalizes_usage_and_cost_without_result_text(self) -> None:
        raw = json.dumps(
            {
                "type": "result",
                "result": "sensitive answer",
                "usage": {
                    "input_tokens": 20,
                    "output_tokens": 5,
                    "cache_creation_input_tokens": 4,
                    "cache_read_input_tokens": 8,
                },
                "total_cost_usd": 0.42,
            }
        )

        normalized = normalize_claude_output(raw)

        self.assertEqual(normalized["usage"]["input_tokens"], 20)
        self.assertEqual(normalized["usage"]["output_tokens"], 5)
        self.assertEqual(normalized["usage"]["cache_creation_input_tokens"], 4)
        self.assertEqual(normalized["usage"]["cache_read_input_tokens"], 8)
        self.assertEqual(normalized["cost_usd"], 0.42)
        self.assertNotIn("sensitive answer", json.dumps(normalized))

    def test_missing_or_invalid_metrics_are_null(self) -> None:
        normalized = normalize_claude_output("not-json")

        self.assertEqual(
            normalized,
            {
                "usage": {
                    "input_tokens": None,
                    "output_tokens": None,
                    "cache_creation_input_tokens": None,
                    "cache_read_input_tokens": None,
                    "cached_input_tokens": None,
                    "cache_write_input_tokens": None,
                    "reasoning_output_tokens": None,
                },
                "cost_usd": None,
            },
        )


class CodexOutputTests(unittest.TestCase):
    def test_normalizes_usage_and_only_records_mcp_names(self) -> None:
        raw = "\n".join(
            [
                json.dumps({"type": "turn.started"}),
                json.dumps(
                    {
                        "type": "item.completed",
                        "item": {
                            "id": "item_1",
                            "type": "mcp_tool_call",
                            "server": "company_codegraph",
                            "tool": "codegraph_search",
                            "arguments": {"query": "sensitive query"},
                            "result": {"content": "sensitive source"},
                            "error": None,
                            "status": "completed",
                        },
                    }
                ),
                json.dumps(
                    {
                        "type": "item.completed",
                        "item": {
                            "id": "item_2",
                            "type": "agent_message",
                            "text": "src/codegraph_harness/bundle.py",
                        },
                    }
                ),
                json.dumps(
                    {
                        "type": "turn.completed",
                        "usage": {
                            "input_tokens": 105,
                            "cached_input_tokens": 80,
                            "cache_write_input_tokens": 2,
                            "output_tokens": 17,
                            "reasoning_output_tokens": 3,
                        },
                    }
                ),
            ]
        )

        normalized = normalize_codex_output(raw)

        self.assertEqual(normalized["usage"]["input_tokens"], 105)
        self.assertEqual(normalized["usage"]["cached_input_tokens"], 80)
        self.assertEqual(normalized["usage"]["reasoning_output_tokens"], 3)
        self.assertEqual(
            normalized["tool_calls"],
            {
                "available": True,
                "count": 1,
                "by_tool": {"company_codegraph.codegraph_search": 1},
            },
        )
        self.assertEqual(normalized["final_text"], "src/codegraph_harness/bundle.py")
        serialized = json.dumps(normalized)
        self.assertNotIn("sensitive query", serialized)
        self.assertNotIn("sensitive source", serialized)

    def test_malformed_mcp_item_makes_count_unavailable(self) -> None:
        raw = "\n".join(
            [
                json.dumps(
                    {
                        "type": "item.completed",
                        "item": {"type": "mcp_tool_call", "arguments": {}},
                    }
                ),
                json.dumps({"type": "turn.completed", "usage": {}}),
            ]
        )
        self.assertEqual(
            normalize_codex_output(raw)["tool_calls"],
            {"available": False, "count": None, "by_tool": {}},
        )


class EvaluationRunnerTests(unittest.TestCase):
    def test_codex_graph_condition_records_oracle_without_final_text(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_path = Path(temporary_directory)
            repo = temporary_path / "repo"
            repo.mkdir()
            harness = temporary_path / "harness"
            harness.mkdir()
            tasks = temporary_path / "tasks.json"
            conditions = temporary_path / "conditions.json"
            _write_json(
                tasks,
                {
                    "schema_version": 1,
                    "tasks": [
                        {
                            "id": "find-entry",
                            "prompt": "Find the entry point.",
                            "oracle": {
                                "required_substrings": [
                                    "src/codegraph_harness/bundle.py"
                                ],
                                "forbidden_substrings": ["outside/repository.py"],
                            },
                        }
                    ],
                },
            )
            _write_json(
                conditions,
                {
                    "schema_version": 1,
                    "conditions": [
                        {
                            "id": "codex-graph-gateway",
                            "client": "codex",
                            "variant": "graph-gateway",
                            "allowed_data_classifications": ["public-fixture"],
                            "command": _codex_command(graph=True),
                        }
                    ],
                },
            )
            stdout = "\n".join(
                [
                    json.dumps(
                        {
                            "type": "item.completed",
                            "item": {
                                "id": "tool",
                                "type": "mcp_tool_call",
                                "server": "company_codegraph",
                                "tool": "codegraph_search",
                                "arguments": {"query": "must not persist"},
                                "result": {"content": "must not persist"},
                                "error": None,
                                "status": "completed",
                            },
                        }
                    ),
                    json.dumps(
                        {
                            "type": "item.completed",
                            "item": {
                                "id": "answer",
                                "type": "agent_message",
                                "text": "src/codegraph_harness/bundle.py",
                            },
                        }
                    ),
                    json.dumps(
                        {
                            "type": "turn.completed",
                            "usage": {
                                "input_tokens": 20,
                                "cached_input_tokens": 5,
                                "output_tokens": 3,
                                "reasoning_output_tokens": 1,
                            },
                        }
                    ),
                ]
            )
            with patch("codegraph_harness.evaluation.subprocess.run") as mocked_run:
                mocked_run.return_value.returncode = 0
                mocked_run.return_value.stdout = stdout
                mocked_run.return_value.stderr = ""
                result = run_evaluation(
                    tasks_path=tasks,
                    conditions_path=conditions,
                    repo=repo,
                    harness_root=harness,
                    output_dir=temporary_path / "output",
                    data_classification="public-fixture",
                )

        run = result["runs"][0]
        self.assertEqual(run["client"], "codex")
        self.assertEqual(run["variant"], "graph-gateway")
        self.assertTrue(run["oracle"]["passed"])
        self.assertEqual(run["tool_calls"]["count"], 1)
        serialized = json.dumps(result)
        self.assertNotIn("must not persist", serialized)
        self.assertNotIn("src/codegraph_harness/bundle.py", serialized)

    def test_failure_does_not_stop_later_tasks_and_sensitive_values_are_hashed(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_path = Path(temporary_directory)
            repo = temporary_path / "sensitive-repo-path"
            repo.mkdir()
            harness = temporary_path / "sensitive-harness-path"
            harness.mkdir()
            output = temporary_path / "output"
            tasks_path = temporary_path / "tasks.json"
            conditions_path = temporary_path / "conditions.json"
            _write_json(
                tasks_path,
                {
                    "schema_version": 1,
                    "tasks": [
                        {"id": "fails", "prompt": "fail-secret"},
                        {"id": "passes", "prompt": "pass-secret"},
                    ],
                },
            )
            _write_json(
                conditions_path,
                {
                    "schema_version": 1,
                    "conditions": [
                        {
                            "id": "baseline",
                            "allowed_data_classifications": ["public-fixture"],
                            "command": _claude_command(),
                        }
                    ],
                },
            )

            result = run_evaluation(
                tasks_path=tasks_path,
                conditions_path=conditions_path,
                repo=repo,
                harness_root=harness,
                output_dir=output,
                data_classification="public-fixture",
                seed=73,
                repetitions=2,
                store_raw_artifacts=True,
            )

            self.assertEqual(result["status"], "completed_with_failures")
            self.assertEqual(result["summary"]["total_runs"], 4)
            self.assertEqual(result["summary"]["succeeded"], 2)
            self.assertEqual(result["summary"]["failed"], 2)
            self.assertEqual({run["repetition"] for run in result["runs"]}, {0, 1})
            self.assertTrue(all(run["seed"] == 73 for run in result["runs"]))

            serialized = (output / "result.json").read_text(encoding="utf-8")
            self.assertNotIn("fail-secret", serialized)
            self.assertNotIn("pass-secret", serialized)
            self.assertNotIn(str(repo), serialized)
            self.assertNotIn(str(harness), serialized)
            self.assertIn(hashlib.sha256(b"fail-secret").hexdigest(), serialized)
            self.assertIn(
                hashlib.sha256(str(repo.resolve()).encode("utf-8")).hexdigest(),
                serialized,
            )
            self.assertIn(
                hashlib.sha256(str(harness.resolve()).encode("utf-8")).hexdigest(),
                serialized,
            )

            raw_artifacts = [
                artifact
                for artifact in result["artifacts"]
                if artifact["kind"] in {"stdout", "stderr"}
            ]
            self.assertEqual(len(raw_artifacts), 8)
            for artifact in raw_artifacts:
                self.assertTrue((output / artifact["relative_path"]).is_file())
                self.assertEqual(len(artifact["sha256"]), 64)
                if os.name != "nt":
                    mode = (output / artifact["relative_path"]).stat().st_mode
                    self.assertEqual(stat.S_IMODE(mode), 0o600)

    def test_prepare_and_mcp_materialization_are_per_condition(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_path = Path(temporary_directory)
            repo = temporary_path / "repo"
            repo.mkdir()
            output = temporary_path / "output"
            tasks_path = temporary_path / "tasks.json"
            conditions_path = temporary_path / "conditions.json"
            prepare_script = (
                "import json,sys; from pathlib import Path; "
                "state=Path(sys.argv[1]); repo=sys.argv[2]; "
                "args=json.loads((state/'mcp.json').read_text())"
                "['mcpServers']['graph']['args']; "
                "assert args[1] == repo and args[3] == str(state); "
                "(state/'ready.txt').write_text('ready', encoding='utf-8')"
            )
            command_script = (
                "import json; "
                "print(json.dumps({'type':'result','usage':{'input_tokens':1}}))"
            )
            _write_json(
                tasks_path,
                {"schema_version": 1, "tasks": [{"id": "one", "prompt": "p"}]},
            )
            _write_json(
                conditions_path,
                {
                    "schema_version": 1,
                    "conditions": [
                        {
                            "id": "graphify-native",
                            "allowed_data_classifications": ["public-fixture"],
                            "prepare_command": [
                                sys.executable,
                                "-c",
                                prepare_script,
                                "{state}",
                                "{repo}",
                            ],
                            "command": [sys.executable, "-c", command_script],
                            "mcp_config": {
                                "mcpServers": {
                                    "graph": {
                                        "command": "adapter",
                                        "args": [
                                            "--repo",
                                            "{repo}",
                                            "--state",
                                            "{state}",
                                        ],
                                    }
                                }
                            },
                        }
                    ],
                },
            )

            result = run_evaluation(
                tasks_path=tasks_path,
                conditions_path=conditions_path,
                repo=repo,
                output_dir=output,
                data_classification="public-fixture",
                seed=1,
                repetitions=1,
                repo_is_disposable_copy=True,
            )

            self.assertEqual(result["status"], "completed")
            self.assertEqual(result["preparations"][0]["status"], "succeeded")
            self.assertEqual(result["summary"]["state_cleanup"], "succeeded")
            self.assertFalse((output / "state").exists())
            mcp_artifacts = [
                artifact
                for artifact in result["artifacts"]
                if artifact["kind"] == "mcp_config"
            ]
            self.assertEqual(len(mcp_artifacts), 1)
            self.assertFalse(mcp_artifacts[0]["stored"])
            self.assertNotIn(str(repo.resolve()), json.dumps(result))

    def test_subprocess_is_never_invoked_through_a_shell(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_path = Path(temporary_directory)
            repo = temporary_path / "repo"
            repo.mkdir()
            tasks_path = temporary_path / "tasks.json"
            conditions_path = temporary_path / "conditions.json"
            _write_json(
                tasks_path,
                {"schema_version": 1, "tasks": [{"id": "one", "prompt": "p"}]},
            )
            _write_json(
                conditions_path,
                {
                    "schema_version": 1,
                    "conditions": [
                        {
                            "id": "baseline",
                            "allowed_data_classifications": ["public-fixture"],
                            "command": [sys.executable, "-c", "print('{}')"],
                        }
                    ],
                },
            )

            with patch("codegraph_harness.evaluation.subprocess.run") as mocked_run:
                mocked_run.return_value.returncode = 0
                mocked_run.return_value.stdout = "{}"
                mocked_run.return_value.stderr = ""
                run_evaluation(
                    tasks_path=tasks_path,
                    conditions_path=conditions_path,
                    repo=repo,
                    output_dir=temporary_path / "output",
                    data_classification="public-fixture",
                )

            self.assertTrue(mocked_run.called)
            self.assertTrue(
                all(call.kwargs["shell"] is False for call in mocked_run.call_args_list)
            )
            task_call = mocked_run.call_args_list[-1]
            self.assertEqual(task_call.kwargs["input"], "p")
            self.assertNotIn("p", task_call.args[0])

    def test_prepare_failure_blocks_only_its_condition(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_path = Path(temporary_directory)
            repo = temporary_path / "repo"
            repo.mkdir()
            tasks_path = temporary_path / "tasks.json"
            conditions_path = temporary_path / "conditions.json"
            success_script = "print('{}')"
            _write_json(
                tasks_path,
                {"schema_version": 1, "tasks": [{"id": "one", "prompt": "p"}]},
            )
            _write_json(
                conditions_path,
                {
                    "schema_version": 1,
                    "conditions": [
                        {
                            "id": "graphify-native",
                            "allowed_data_classifications": ["public-fixture"],
                            "prepare_command": [
                                sys.executable,
                                "-c",
                                "raise SystemExit(8)",
                            ],
                            "command": [sys.executable, "-c", success_script],
                        },
                        {
                            "id": "baseline",
                            "allowed_data_classifications": ["public-fixture"],
                            "command": [sys.executable, "-c", success_script],
                        },
                    ],
                },
            )

            result = run_evaluation(
                tasks_path=tasks_path,
                conditions_path=conditions_path,
                repo=repo,
                output_dir=temporary_path / "output",
                data_classification="public-fixture",
                repo_is_disposable_copy=True,
            )

            statuses = {run["condition"]: run["status"] for run in result["runs"]}
            self.assertEqual(statuses["graphify-native"], "blocked")
            self.assertEqual(statuses["baseline"], "succeeded")
            self.assertEqual(result["summary"]["total_runs"], 2)

    def test_cli_returns_nonzero_for_partial_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_path = Path(temporary_directory)
            repo = temporary_path / "repo"
            repo.mkdir()
            tasks_path = temporary_path / "tasks.json"
            conditions_path = temporary_path / "conditions.json"
            _write_json(
                tasks_path,
                {
                    "schema_version": 1,
                    "tasks": [{"id": "bad", "prompt": "fail-secret"}],
                },
            )
            _write_json(
                conditions_path,
                {
                    "schema_version": 1,
                    "conditions": [
                        {
                            "id": "baseline",
                            "allowed_data_classifications": ["public-fixture"],
                            "command": _claude_command(),
                        }
                    ],
                },
            )

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                exit_code = run_evaluation_cli(
                    [
                        "--tasks",
                        str(tasks_path),
                        "--conditions",
                        str(conditions_path),
                        "--repo",
                        str(repo),
                        "--output-dir",
                        str(temporary_path / "output"),
                        "--data-classification",
                        "public-fixture",
                    ]
                )

            self.assertEqual(exit_code, 1)
            response = json.loads(stdout.getvalue())
            self.assertEqual(
                set(response),
                {"status", "summary", "next_actions", "artifacts"},
            )
            self.assertTrue(
                any(
                    "--store-raw-artifacts" in action
                    for action in response["next_actions"]
                )
            )
            self.assertFalse(
                any(
                    "Inspect failed run artifacts" in action
                    for action in response["next_actions"]
                )
            )

    def test_example_configuration_declares_all_comparison_conditions(self) -> None:
        repository = Path(__file__).resolve().parents[1]
        conditions_path = repository / "evaluation/configs/conditions.example.json"
        tasks_path = repository / "evaluation/tasks/smoke.json"
        conditions = json.loads(conditions_path.read_text())
        task_suite = json.loads(tasks_path.read_text())

        self.assertEqual(
            {condition["id"] for condition in conditions["conditions"]},
            {
                "baseline",
                "graphify-native",
                "codebase-memory-native",
                "graphify-hybrid",
                "codebase-memory-hybrid",
            },
        )
        self.assertGreaterEqual(len(task_suite["tasks"]), 3)
        for condition in conditions["conditions"]:
            command = condition["command"]
            self.assertIn("--bare", command)
            self.assertIn("--no-session-persistence", command)
            self.assertIn("--strict-mcp-config", command)
            self.assertNotIn("{prompt}", command)
            if condition["id"].endswith("-hybrid"):
                self.assertIn("--plugin-dir", command)
                self.assertIn("--append-system-prompt-file", command)
            else:
                self.assertNotIn("--plugin-dir", command)
                self.assertNotIn("--append-system-prompt-file", command)
        codebase_memory = next(
            condition
            for condition in conditions["conditions"]
            if condition["id"] == "codebase-memory-native"
        )
        self.assertEqual(len(codebase_memory["prepare_commands"]), 4)

        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_path = Path(temporary_directory)
            repo = temporary_path / "repo"
            repo.mkdir()
            with patch("codegraph_harness.evaluation.subprocess.run") as mocked_run:
                mocked_run.return_value.returncode = 0
                mocked_run.return_value.stdout = "{}"
                mocked_run.return_value.stderr = ""
                result = run_evaluation(
                    tasks_path=tasks_path,
                    conditions_path=conditions_path,
                    repo=repo,
                    output_dir=temporary_path / "output",
                    data_classification="public-fixture",
                    selected_conditions=["baseline"],
                )

        self.assertEqual(result["status"], "completed")

    def test_company_source_is_disabled_even_with_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_path = Path(temporary_directory)
            repo = temporary_path / "repo"
            repo.mkdir()
            tasks_path = temporary_path / "tasks.json"
            conditions_path = temporary_path / "conditions.json"
            _write_json(
                tasks_path,
                {"schema_version": 1, "tasks": [{"id": "one", "prompt": "p"}]},
            )
            _write_json(
                conditions_path,
                {
                    "schema_version": 1,
                    "conditions": [
                        {
                            "id": "baseline",
                            "allowed_data_classifications": ["company-source"],
                            "command": [sys.executable, "-c", "print('{}')"],
                        }
                    ],
                },
            )

            for evidence_id in (None, "SEC-EVIDENCE-secret-value"):
                with self.subTest(evidence_id=evidence_id):
                    with (
                        patch(
                            "codegraph_harness.evaluation._load_json"
                        ) as mocked_load_json,
                        patch(
                            "codegraph_harness.evaluation.subprocess.run"
                        ) as mocked_run,
                    ):
                        with self.assertRaisesRegex(
                            EvaluationConfigError,
                            "company-source is disabled in this release",
                        ):
                            run_evaluation(
                                tasks_path=tasks_path,
                                conditions_path=conditions_path,
                                repo=repo,
                                output_dir=temporary_path / "rejected",
                                data_classification="company-source",
                                security_evidence_id=evidence_id,
                            )

                    mocked_load_json.assert_not_called()
                    mocked_run.assert_not_called()
            self.assertFalse((temporary_path / "rejected").exists())

    def test_condition_data_policy_blocks_company_source_before_execution(self) -> None:
        repository = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_path = Path(temporary_directory)
            repo = temporary_path / "disposable-repo"
            repo.mkdir()
            with patch("codegraph_harness.evaluation.subprocess.run") as mocked_run:
                with self.assertRaises(EvaluationConfigError):
                    run_evaluation(
                        tasks_path=repository / "evaluation/tasks/smoke.json",
                        conditions_path=(
                            repository / "evaluation/configs/conditions.example.json"
                        ),
                        repo=repo,
                        output_dir=temporary_path / "output",
                        data_classification="company-source",
                        security_evidence_id="approved-route",
                        selected_conditions=["graphify-native"],
                        repo_is_disposable_copy=True,
                    )

            mocked_run.assert_not_called()

    def test_graphify_native_requires_disposable_repo_acknowledgement(self) -> None:
        repository = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_path = Path(temporary_directory)
            repo = temporary_path / "original-repo"
            repo.mkdir()
            with patch("codegraph_harness.evaluation.subprocess.run") as mocked_run:
                with self.assertRaises(EvaluationConfigError):
                    run_evaluation(
                        tasks_path=repository / "evaluation/tasks/smoke.json",
                        conditions_path=(
                            repository / "evaluation/configs/conditions.example.json"
                        ),
                        repo=repo,
                        output_dir=temporary_path / "output",
                        data_classification="public-fixture",
                        selected_conditions=["graphify-native"],
                    )

            mocked_run.assert_not_called()

    def test_prepare_and_command_environment_inheritance_are_separate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_path = Path(temporary_directory)
            repo = temporary_path / "repo"
            repo.mkdir()
            tasks_path = temporary_path / "tasks.json"
            conditions_path = temporary_path / "conditions.json"
            _write_json(
                tasks_path,
                {"schema_version": 1, "tasks": [{"id": "one", "prompt": "p"}]},
            )
            _write_json(
                conditions_path,
                {
                    "schema_version": 1,
                    "conditions": [
                        {
                            "id": "baseline",
                            "allowed_data_classifications": ["public-fixture"],
                            "prepare_command": [
                                sys.executable,
                                "-c",
                                "print('{}')",
                            ],
                            "command": [sys.executable, "-c", "print('{}')"],
                            "environment": {"EXPLICIT_NAME": "explicit-secret"},
                            "prepare_inherit_environment": ["PREP_ONLY"],
                            "command_inherit_environment": ["COMMAND_ONLY"],
                        }
                    ],
                },
            )
            parent_environment = {
                "PATH": os.environ.get("PATH", ""),
                "PREP_ONLY": "prepare-secret",
                "COMMAND_ONLY": "command-secret",
                "UNDECLARED_SECRET": "must-not-leak",
            }

            with patch.dict(os.environ, parent_environment, clear=True):
                with patch("codegraph_harness.evaluation.subprocess.run") as mocked_run:
                    mocked_run.return_value.returncode = 0
                    mocked_run.return_value.stdout = "{}"
                    mocked_run.return_value.stderr = ""
                    result = run_evaluation(
                        tasks_path=tasks_path,
                        conditions_path=conditions_path,
                        repo=repo,
                        output_dir=temporary_path / "output",
                        data_classification="public-fixture",
                    )

            prepare_environment = mocked_run.call_args_list[0].kwargs["env"]
            command_environment = mocked_run.call_args_list[1].kwargs["env"]
            self.assertIn("PREP_ONLY", prepare_environment)
            self.assertNotIn("COMMAND_ONLY", prepare_environment)
            self.assertIn("COMMAND_ONLY", command_environment)
            self.assertNotIn("PREP_ONLY", command_environment)
            self.assertNotIn("UNDECLARED_SECRET", prepare_environment)
            self.assertNotIn("UNDECLARED_SECRET", command_environment)
            for home_name in ("HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA"):
                self.assertNotIn(home_name, prepare_environment)
                self.assertNotIn(home_name, command_environment)
                self.assertNotIn(
                    home_name,
                    result["evaluation"]["environment_policy"]["baseline"][
                        "minimum_environment_names"
                    ],
                )
            serialized = json.dumps(result)
            for secret in parent_environment.values():
                self.assertNotIn(secret, serialized)
            self.assertNotIn("explicit-secret", serialized)

    def test_home_environment_inheritance_is_rejected_case_insensitively(self) -> None:
        forbidden_names = ("HOME", "userProfile", "AppData", "localappdata")
        for field in (
            "prepare_inherit_environment",
            "command_inherit_environment",
        ):
            for forbidden_name in forbidden_names:
                with self.subTest(field=field, forbidden_name=forbidden_name):
                    with tempfile.TemporaryDirectory() as temporary_directory:
                        temporary_path = Path(temporary_directory)
                        repo = temporary_path / "repo"
                        repo.mkdir()
                        tasks_path = temporary_path / "tasks.json"
                        conditions_path = temporary_path / "conditions.json"
                        _write_json(
                            tasks_path,
                            {
                                "schema_version": 1,
                                "tasks": [{"id": "one", "prompt": "p"}],
                            },
                        )
                        _write_json(
                            conditions_path,
                            {
                                "schema_version": 1,
                                "conditions": [
                                    {
                                        "id": "baseline",
                                        "allowed_data_classifications": [
                                            "public-fixture"
                                        ],
                                        "command": [
                                            sys.executable,
                                            "-c",
                                            "print('{}')",
                                        ],
                                        field: [forbidden_name],
                                    }
                                ],
                            },
                        )

                        with patch(
                            "codegraph_harness.evaluation.subprocess.run"
                        ) as mocked_run:
                            with self.assertRaisesRegex(
                                EvaluationConfigError,
                                "may not inherit user profile directories",
                            ):
                                run_evaluation(
                                    tasks_path=tasks_path,
                                    conditions_path=conditions_path,
                                    repo=repo,
                                    output_dir=temporary_path / "output",
                                    data_classification="public-fixture",
                                )

                        mocked_run.assert_not_called()

    def test_explicit_environment_names_and_collisions_are_rejected(self) -> None:
        invalid_cases = (
            ({"environment": {"BAD=NAME": "value"}}, "valid OS names"),
            ({"environment": {"BAD\0NAME": "value"}}, "valid OS names"),
            (
                {"environment": {"TOKEN": "one", "token": "two"}},
                "case-insensitive duplicates",
            ),
            (
                {"environment": {"pAtH": "override"}},
                "reserved runner environment names",
            ),
            (
                {"environment": {"Home": "override"}},
                "reserved runner environment names",
            ),
            (
                {
                    "environment": {"TOKEN": "explicit"},
                    "prepare_inherit_environment": ["token"],
                },
                "must not overlap explicit environment names",
            ),
            (
                {
                    "environment": {"TOKEN": "explicit"},
                    "command_inherit_environment": ["ToKeN"],
                },
                "must not overlap explicit environment names",
            ),
            (
                {"prepare_inherit_environment": ["pAtH"]},
                "already inherited by the runner",
            ),
        )
        for overrides, expected_error in invalid_cases:
            with self.subTest(overrides=overrides):
                with tempfile.TemporaryDirectory() as temporary_directory:
                    temporary_path = Path(temporary_directory)
                    repo = temporary_path / "repo"
                    repo.mkdir()
                    tasks_path = temporary_path / "tasks.json"
                    conditions_path = temporary_path / "conditions.json"
                    _write_json(
                        tasks_path,
                        {
                            "schema_version": 1,
                            "tasks": [{"id": "one", "prompt": "p"}],
                        },
                    )
                    condition = {
                        "id": "baseline",
                        "allowed_data_classifications": ["public-fixture"],
                        "command": [sys.executable, "-c", "print('{}')"],
                        **overrides,
                    }
                    _write_json(
                        conditions_path,
                        {"schema_version": 1, "conditions": [condition]},
                    )

                    with patch(
                        "codegraph_harness.evaluation.subprocess.run"
                    ) as mocked_run:
                        with self.assertRaisesRegex(
                            EvaluationConfigError, expected_error
                        ):
                            run_evaluation(
                                tasks_path=tasks_path,
                                conditions_path=conditions_path,
                                repo=repo,
                                output_dir=temporary_path / "output",
                                data_classification="public-fixture",
                            )

                    mocked_run.assert_not_called()

    def test_state_is_removed_when_evaluation_is_interrupted(self) -> None:
        for raised_error in (RuntimeError("unexpected"), KeyboardInterrupt()):
            with self.subTest(error_type=type(raised_error).__name__):
                with tempfile.TemporaryDirectory() as temporary_directory:
                    temporary_path = Path(temporary_directory)
                    repo = temporary_path / "repo"
                    repo.mkdir()
                    output = temporary_path / "output"
                    tasks_path = temporary_path / "tasks.json"
                    conditions_path = temporary_path / "conditions.json"
                    _write_json(
                        tasks_path,
                        {
                            "schema_version": 1,
                            "tasks": [{"id": "one", "prompt": "p"}],
                        },
                    )
                    _write_json(
                        conditions_path,
                        {
                            "schema_version": 1,
                            "conditions": [
                                {
                                    "id": "baseline",
                                    "allowed_data_classifications": ["public-fixture"],
                                    "command": [
                                        sys.executable,
                                        "-c",
                                        "print('{}')",
                                    ],
                                    "mcp_config": {"mcpServers": {}},
                                }
                            ],
                        },
                    )

                    with patch(
                        "codegraph_harness.evaluation._run_process",
                        side_effect=raised_error,
                    ):
                        with self.assertRaises(type(raised_error)):
                            run_evaluation(
                                tasks_path=tasks_path,
                                conditions_path=conditions_path,
                                repo=repo,
                                output_dir=output,
                                data_classification="public-fixture",
                            )

                    self.assertFalse((output / "state").exists())

    def test_candidate_policy_cannot_be_configured_for_company_source(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_path = Path(temporary_directory)
            repo = temporary_path / "repo"
            repo.mkdir()
            tasks_path = temporary_path / "tasks.json"
            conditions_path = temporary_path / "conditions.json"
            _write_json(
                tasks_path,
                {"schema_version": 1, "tasks": [{"id": "one", "prompt": "p"}]},
            )
            _write_json(
                conditions_path,
                {
                    "schema_version": 1,
                    "conditions": [
                        {
                            "id": "graphify-hybrid",
                            "allowed_data_classifications": [
                                "public-fixture",
                                "company-source",
                            ],
                            "command": [sys.executable, "-c", "print('{}')"],
                        }
                    ],
                },
            )

            with patch("codegraph_harness.evaluation.subprocess.run") as mocked_run:
                with self.assertRaisesRegex(
                    EvaluationConfigError, "restricted to public-fixture"
                ):
                    run_evaluation(
                        tasks_path=tasks_path,
                        conditions_path=conditions_path,
                        repo=repo,
                        output_dir=temporary_path / "output",
                        data_classification="public-fixture",
                    )

            mocked_run.assert_not_called()

    def test_nonempty_output_directory_is_rejected_without_deleting_it(self) -> None:
        repository = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_path = Path(temporary_directory)
            repo = temporary_path / "repo"
            repo.mkdir()
            output = temporary_path / "output"
            output.mkdir()
            marker = output / "state" / "keep.txt"
            marker.parent.mkdir()
            marker.write_text("keep")

            with self.assertRaises(EvaluationConfigError):
                run_evaluation(
                    tasks_path=repository / "evaluation/tasks/smoke.json",
                    conditions_path=(
                        repository / "evaluation/configs/conditions.example.json"
                    ),
                    repo=repo,
                    output_dir=output,
                    data_classification="public-fixture",
                    selected_conditions=["baseline"],
                )

            self.assertEqual(marker.read_text(), "keep")

    @unittest.skipIf(jsonschema is None, "jsonschema is not installed")
    def test_examples_and_generated_result_match_json_contracts(self) -> None:
        repository = Path(__file__).resolve().parents[1]
        tasks = json.loads((repository / "evaluation/tasks/smoke.json").read_text())
        conditions = json.loads(
            (repository / "evaluation/configs/conditions.example.json").read_text()
        )
        task_schema = json.loads(
            (repository / "contracts/evaluation-tasks.schema.json").read_text()
        )
        condition_schema = json.loads(
            (repository / "contracts/evaluation-conditions.schema.json").read_text()
        )
        result_schema = json.loads(
            (repository / "contracts/evaluation-result.schema.json").read_text()
        )

        jsonschema.validate(tasks, task_schema)
        jsonschema.validate(conditions, condition_schema)
        for inherit_field in (
            "prepare_inherit_environment",
            "command_inherit_environment",
        ):
            invalid_conditions = {
                "schema_version": 1,
                "conditions": [
                    {
                        "id": "baseline",
                        "allowed_data_classifications": ["public-fixture"],
                        "command": ["runner"],
                        inherit_field: ["uSeRpRoFiLe"],
                    }
                ],
            }
            with self.subTest(schema_field=inherit_field):
                with self.assertRaises(jsonschema.ValidationError):
                    jsonschema.validate(invalid_conditions, condition_schema)
        invalid_condition_fragments = (
            {"allowed_data_classifications": ["company-source"]},
            {"environment": {"BAD=NAME": "value"}},
            {"environment": {"BAD\0NAME": "value"}},
            {"environment": {"pAtH": "value"}},
            {"environment": {"Home": "value"}},
        )
        for invalid_fragment in invalid_condition_fragments:
            invalid_condition = {
                "id": "baseline",
                "allowed_data_classifications": ["public-fixture"],
                "command": ["runner"],
                **invalid_fragment,
            }
            with self.subTest(schema_fragment=invalid_fragment):
                with self.assertRaises(jsonschema.ValidationError):
                    jsonschema.validate(
                        {"schema_version": 1, "conditions": [invalid_condition]},
                        condition_schema,
                    )

        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_path = Path(temporary_directory)
            repo = temporary_path / "repo"
            repo.mkdir()
            with patch("codegraph_harness.evaluation.subprocess.run") as mocked_run:
                mocked_run.return_value.returncode = 0
                mocked_run.return_value.stdout = "{}"
                mocked_run.return_value.stderr = ""
                result = run_evaluation(
                    tasks_path=repository / "evaluation/tasks/smoke.json",
                    conditions_path=(
                        repository / "evaluation/configs/conditions.example.json"
                    ),
                    repo=repo,
                    output_dir=temporary_path / "output",
                    data_classification="public-fixture",
                    selected_conditions=["baseline"],
                )

        jsonschema.validate(result, result_schema)
        serialized = json.dumps(result)
        for forbidden_key in (
            '"prompt":',
            '"repo":',
            '"harness_root":',
            '"security_evidence_id":',
        ):
            self.assertNotIn(forbidden_key, serialized)


if __name__ == "__main__":
    unittest.main()
