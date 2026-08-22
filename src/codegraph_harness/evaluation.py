"""Deterministic, privacy-conscious runner for code-graph evaluations."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import random
import re
import shutil
import subprocess
import sys
import time
from collections.abc import Mapping, Sequence
from typing import Any

SUPPORTED_CONDITIONS = frozenset(
    {
        "baseline",
        "graphify-native",
        "codebase-memory-native",
        "graphify-hybrid",
        "codebase-memory-hybrid",
    }
)
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
_PLACEHOLDERS = frozenset({"repo", "state", "prompt", "harness"})
_TEMPLATE_FIELD = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*[^{}]*)\}")
_ENVIRONMENT_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_DATA_CLASSIFICATIONS = frozenset({"public-fixture", "company-source"})
_PUBLIC_FIXTURE_ONLY_CONDITIONS = SUPPORTED_CONDITIONS
_FORBIDDEN_USER_PROFILE_ENVIRONMENT_NAMES = frozenset(
    {"home", "userprofile", "appdata", "localappdata"}
)
_MINIMUM_ENVIRONMENT_NAMES = frozenset(
    {
        "COMSPEC",
        "LANG",
        "LC_ALL",
        "PATH",
        "PATHEXT",
        "SystemRoot",
        "TEMP",
        "TMP",
        "TMPDIR",
        "WINDIR",
    }
)
_MINIMUM_ENVIRONMENT_NAMES_CASEFOLDED = frozenset(
    name.casefold() for name in _MINIMUM_ENVIRONMENT_NAMES
)
_RESERVED_ENVIRONMENT_NAMES = (
    _FORBIDDEN_USER_PROFILE_ENVIRONMENT_NAMES | _MINIMUM_ENVIRONMENT_NAMES_CASEFOLDED
)


class EvaluationConfigError(ValueError):
    """Raised when an evaluation input violates the public JSON contract."""


class _StateCleanup:
    """Own and remove only the state directory created by this evaluation."""

    def __init__(self) -> None:
        self._path: Path | None = None

    def arm(self, path: Path) -> None:
        if self._path is not None:
            raise RuntimeError("state cleanup is already armed")
        self._path = path

    def cleanup(self) -> str:
        path = self._path
        self._path = None
        if path is None:
            return "succeeded"
        try:
            shutil.rmtree(path)
        except FileNotFoundError:
            pass
        except OSError:
            return "failed"
        return "succeeded"


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_text(value: str) -> str:
    return _sha256_bytes(value.encode("utf-8"))


def _validate_template(value: str) -> None:
    for match in _TEMPLATE_FIELD.finditer(value):
        if match.group(1) not in _PLACEHOLDERS:
            raise EvaluationConfigError(
                "command templates may only use repo, state, prompt, and harness"
            )


def _render_string(value: str, replacements: Mapping[str, str]) -> str:
    _validate_template(value)
    if set(replacements) != _PLACEHOLDERS:
        raise EvaluationConfigError(
            "template replacements must contain repo, state, prompt, and harness"
        )
    rendered = value
    for placeholder in _PLACEHOLDERS:
        rendered = rendered.replace(f"{{{placeholder}}}", replacements[placeholder])
    return rendered


def render_command(
    command: Sequence[str], replacements: Mapping[str, str]
) -> list[str]:
    """Render an argv array without invoking a command shell."""

    if not isinstance(command, list) or not command:
        raise EvaluationConfigError("commands must be non-empty JSON arrays")
    if not all(isinstance(item, str) for item in command):
        raise EvaluationConfigError("every command argument must be a string")
    return [_render_string(item, replacements) for item in command]


def _metric_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value >= 0:
        return value
    if isinstance(value, float) and value >= 0 and value.is_integer():
        return int(value)
    return None


def _metric_float(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if number < 0 or not math.isfinite(number):
        return None
    return number


def _null_metrics() -> dict[str, object]:
    return {
        "usage": {
            "input_tokens": None,
            "output_tokens": None,
            "cache_creation_input_tokens": None,
            "cache_read_input_tokens": None,
        },
        "cost_usd": None,
    }


def _claude_payload(raw_stdout: str) -> dict[str, Any] | None:
    try:
        decoded = json.loads(raw_stdout)
    except (json.JSONDecodeError, TypeError):
        decoded = None
    if isinstance(decoded, dict):
        return decoded
    if isinstance(decoded, list):
        dictionaries = [item for item in decoded if isinstance(item, dict)]
        result_items = [item for item in dictionaries if item.get("type") == "result"]
        if result_items:
            return result_items[-1]
        if dictionaries:
            return dictionaries[-1]
        return None

    dictionaries = []
    for line in raw_stdout.splitlines():
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            dictionaries.append(item)
    result_items = [item for item in dictionaries if item.get("type") == "result"]
    if result_items:
        return result_items[-1]
    if dictionaries:
        return dictionaries[-1]
    return None


def normalize_claude_output(raw_stdout: str) -> dict[str, object]:
    """Extract only comparable usage and cost fields from Claude JSON output."""

    payload = _claude_payload(raw_stdout)
    if payload is None:
        return _null_metrics()
    usage_value = payload.get("usage")
    usage = usage_value if isinstance(usage_value, dict) else {}
    return {
        "usage": {
            "input_tokens": _metric_int(usage.get("input_tokens")),
            "output_tokens": _metric_int(usage.get("output_tokens")),
            "cache_creation_input_tokens": _metric_int(
                usage.get("cache_creation_input_tokens")
            ),
            "cache_read_input_tokens": _metric_int(
                usage.get("cache_read_input_tokens")
            ),
        },
        "cost_usd": _metric_float(
            payload.get("total_cost_usd", payload.get("cost_usd"))
        ),
    }


def _load_json(path: Path, label: str) -> tuple[dict[str, Any], str]:
    try:
        raw = path.read_bytes()
    except OSError as error:
        raise EvaluationConfigError(f"could not read {label} JSON") from error
    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError as error:
        raise EvaluationConfigError(f"invalid {label} JSON") from error
    if not isinstance(decoded, dict):
        raise EvaluationConfigError(f"{label} JSON must contain an object")
    return decoded, _sha256_bytes(raw)


def _validate_id(value: object, label: str) -> str:
    if not isinstance(value, str) or not _SAFE_ID.fullmatch(value):
        raise EvaluationConfigError(f"{label} must be a filesystem-safe identifier")
    return value


def _validate_timeout(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise EvaluationConfigError(f"{label} must be a positive number")
    return float(value)


def _validate_tasks(value: dict[str, Any]) -> list[dict[str, Any]]:
    if value.get("schema_version") != 1:
        raise EvaluationConfigError("task suite schema_version must be 1")
    raw_tasks = value.get("tasks")
    if not isinstance(raw_tasks, list) or not raw_tasks:
        raise EvaluationConfigError("task suite must contain at least one task")
    tasks = []
    seen = set()
    for raw_task in raw_tasks:
        if not isinstance(raw_task, dict):
            raise EvaluationConfigError("each task must be an object")
        task_id = _validate_id(raw_task.get("id"), "task id")
        if task_id in seen:
            raise EvaluationConfigError("task ids must be unique")
        seen.add(task_id)
        prompt = raw_task.get("prompt")
        if not isinstance(prompt, str):
            raise EvaluationConfigError("task prompts must be strings")
        task: dict[str, Any] = {"id": task_id, "prompt": prompt}
        if "timeout_seconds" in raw_task:
            task["timeout_seconds"] = _validate_timeout(
                raw_task["timeout_seconds"], "task timeout_seconds"
            )
        tasks.append(task)
    return tasks


def _validate_environment(value: object) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, dict) or not all(
        isinstance(key, str) and isinstance(item, str) for key, item in value.items()
    ):
        raise EvaluationConfigError("environment must map strings to strings")
    names = list(value)
    if not all(_ENVIRONMENT_NAME.fullmatch(name) for name in names):
        raise EvaluationConfigError("environment keys must be valid OS names")
    casefolded = [name.casefold() for name in names]
    if len(casefolded) != len(set(casefolded)):
        raise EvaluationConfigError(
            "environment keys must not contain case-insensitive duplicates"
        )
    if _RESERVED_ENVIRONMENT_NAMES.intersection(casefolded):
        raise EvaluationConfigError(
            "environment keys may not use reserved runner environment names"
        )
    for item in value.values():
        _validate_template(item)
    return dict(value)


def _validate_environment_names(value: object, label: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or not all(
        isinstance(item, str) and _ENVIRONMENT_NAME.fullmatch(item) for item in value
    ):
        raise EvaluationConfigError(f"{label} must be an array of environment names")
    casefolded = [item.casefold() for item in value]
    if len(casefolded) != len(set(casefolded)):
        raise EvaluationConfigError(f"{label} must not contain duplicates")
    if _FORBIDDEN_USER_PROFILE_ENVIRONMENT_NAMES.intersection(casefolded):
        raise EvaluationConfigError(f"{label} may not inherit user profile directories")
    if _MINIMUM_ENVIRONMENT_NAMES_CASEFOLDED.intersection(casefolded):
        raise EvaluationConfigError(
            f"{label} contains names already inherited by the runner"
        )
    return list(value)


def _validate_environment_overlap(
    environment: Mapping[str, str], inherited_names: Sequence[str], label: str
) -> None:
    explicit_names = {name.casefold() for name in environment}
    inherited_casefolded = {name.casefold() for name in inherited_names}
    if explicit_names.intersection(inherited_casefolded):
        raise EvaluationConfigError(
            f"{label} must not overlap explicit environment names"
        )


def _validate_mcp_value(value: object) -> None:
    if isinstance(value, str):
        _validate_template(value)
        return
    if isinstance(value, list):
        for item in value:
            _validate_mcp_value(item)
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise EvaluationConfigError("MCP configuration keys must be strings")
            _validate_mcp_value(item)
        return
    if value is not None and not isinstance(value, (bool, int, float)):
        raise EvaluationConfigError("MCP configuration contains an unsupported value")


def _contains_prompt_placeholder(value: object) -> bool:
    if isinstance(value, str):
        return "{prompt}" in value
    if isinstance(value, list):
        return any(_contains_prompt_placeholder(item) for item in value)
    if isinstance(value, dict):
        return any(_contains_prompt_placeholder(item) for item in value.values())
    return False


def _validate_claude_command(condition_id: str, command: list[str]) -> None:
    executable = command[0].replace("\\", "/").rsplit("/", 1)[-1].casefold()
    if executable not in {"claude", "claude.exe"}:
        return
    required_flags = {
        "--bare",
        "--no-session-persistence",
        "--strict-mcp-config",
        "--mcp-config",
        "--output-format",
        "-p",
    }
    if not required_flags.issubset(command):
        raise EvaluationConfigError(
            "Claude commands must use bare, non-persistent, strict MCP JSON mode"
        )
    output_index = command.index("--output-format")
    if output_index + 1 >= len(command) or command[output_index + 1] != "json":
        raise EvaluationConfigError("Claude output format must be json")
    forbidden_policy_prefixes = (
        "--allowedTools",
        "--disallowedTools",
        "--permission-mode",
        "--tools",
    )
    if any(argument.startswith(forbidden_policy_prefixes) for argument in command):
        raise EvaluationConfigError(
            "condition commands may not override the common permission/tool policy"
        )
    hybrid = condition_id.endswith("-hybrid")
    plugin_flags = {"--plugin-dir", "--append-system-prompt-file"}
    if hybrid and not plugin_flags.issubset(command):
        raise EvaluationConfigError(
            "hybrid Claude commands must load the evaluator plugin and Rule"
        )
    if not hybrid and plugin_flags.intersection(command):
        raise EvaluationConfigError(
            "native and baseline commands must not load hybrid plugin or Rule assets"
        )


def _validate_conditions(value: dict[str, Any]) -> list[dict[str, Any]]:
    if value.get("schema_version") != 1:
        raise EvaluationConfigError("conditions schema_version must be 1")
    raw_conditions = value.get("conditions")
    if not isinstance(raw_conditions, list) or not raw_conditions:
        raise EvaluationConfigError("conditions must contain at least one condition")
    conditions = []
    seen = set()
    for raw_condition in raw_conditions:
        if not isinstance(raw_condition, dict):
            raise EvaluationConfigError("each condition must be an object")
        condition_id = _validate_id(raw_condition.get("id"), "condition id")
        if condition_id not in SUPPORTED_CONDITIONS:
            raise EvaluationConfigError("condition id is not supported")
        if condition_id in seen:
            raise EvaluationConfigError("condition ids must be unique")
        seen.add(condition_id)
        allowed_data_classifications_value = raw_condition.get(
            "allowed_data_classifications"
        )
        if not isinstance(allowed_data_classifications_value, list) or not (
            allowed_data_classifications_value
        ):
            raise EvaluationConfigError(
                "allowed_data_classifications must be a non-empty array"
            )
        if not all(
            isinstance(item, str) and item in _DATA_CLASSIFICATIONS
            for item in allowed_data_classifications_value
        ):
            raise EvaluationConfigError(
                "allowed_data_classifications contains an unsupported value"
            )
        if len(allowed_data_classifications_value) != len(
            set(allowed_data_classifications_value)
        ):
            raise EvaluationConfigError(
                "allowed_data_classifications must not contain duplicates"
            )
        if (
            condition_id in _PUBLIC_FIXTURE_ONLY_CONDITIONS
            and allowed_data_classifications_value != ["public-fixture"]
        ):
            raise EvaluationConfigError(
                f"{condition_id} is restricted to public-fixture in this release"
            )
        command = raw_condition.get("command")
        if not isinstance(command, list):
            raise EvaluationConfigError("command must be a JSON array")
        render_command(
            command,
            {
                "repo": "repo",
                "state": "state",
                "prompt": "prompt",
                "harness": "harness",
            },
        )
        if _contains_prompt_placeholder(command):
            raise EvaluationConfigError("task prompts must be provided through stdin")
        _validate_claude_command(condition_id, command)
        prepare_command = raw_condition.get("prepare_command")
        prepare_commands_value = raw_condition.get("prepare_commands")
        if prepare_command is not None and prepare_commands_value is not None:
            raise EvaluationConfigError(
                "use prepare_command or prepare_commands, not both"
            )
        if prepare_commands_value is not None:
            if not isinstance(prepare_commands_value, list) or not all(
                isinstance(item, list) for item in prepare_commands_value
            ):
                raise EvaluationConfigError(
                    "prepare_commands must be an array of command arrays"
                )
            prepare_commands = list(prepare_commands_value)
        elif prepare_command is not None:
            if not isinstance(prepare_command, list):
                raise EvaluationConfigError("prepare_command must be a JSON array")
            prepare_commands = [prepare_command]
        else:
            prepare_commands = []
        for candidate in prepare_commands:
            render_command(
                candidate,
                {
                    "repo": "repo",
                    "state": "state",
                    "prompt": "prompt",
                    "harness": "harness",
                },
            )
            if _contains_prompt_placeholder(candidate):
                raise EvaluationConfigError(
                    "prepare commands must not receive the task prompt"
                )
        timeout = _validate_timeout(
            raw_condition.get("timeout_seconds", 900),
            "condition timeout_seconds",
        )
        environment = _validate_environment(raw_condition.get("environment"))
        if _contains_prompt_placeholder(environment):
            raise EvaluationConfigError(
                "task prompts must not be placed in child environment variables"
            )
        prepare_inherit_environment = _validate_environment_names(
            raw_condition.get("prepare_inherit_environment"),
            "prepare_inherit_environment",
        )
        command_inherit_environment = _validate_environment_names(
            raw_condition.get("command_inherit_environment"),
            "command_inherit_environment",
        )
        _validate_environment_overlap(
            environment,
            prepare_inherit_environment,
            "prepare_inherit_environment",
        )
        _validate_environment_overlap(
            environment,
            command_inherit_environment,
            "command_inherit_environment",
        )
        mcp_config = raw_condition.get("mcp_config")
        if mcp_config is not None:
            if not isinstance(mcp_config, dict):
                raise EvaluationConfigError("mcp_config must be an object")
            _validate_mcp_value(mcp_config)
            if _contains_prompt_placeholder(mcp_config):
                raise EvaluationConfigError(
                    "task prompts must not be materialized into MCP configuration"
                )
        conditions.append(
            {
                "id": condition_id,
                "allowed_data_classifications": list(
                    allowed_data_classifications_value
                ),
                "command": list(command),
                "prepare_commands": [list(item) for item in prepare_commands],
                "timeout_seconds": timeout,
                "environment": environment,
                "prepare_inherit_environment": prepare_inherit_environment,
                "command_inherit_environment": command_inherit_environment,
                "mcp_config": mcp_config,
            }
        )
    return conditions


def _render_json_value(value: object, replacements: Mapping[str, str]) -> object:
    if isinstance(value, str):
        return _render_string(value, replacements)
    if isinstance(value, list):
        return [_render_json_value(item, replacements) for item in value]
    if isinstance(value, dict):
        return {
            key: _render_json_value(item, replacements) for key, item in value.items()
        }
    return value


def _write_text_artifact(
    output_dir: Path,
    relative_path: Path,
    content: str,
    kind: str,
    *,
    store: bool = True,
) -> dict[str, object]:
    artifact: dict[str, object] = {
        "kind": kind,
        "sha256": _sha256_text(content),
        "stored": store,
    }
    if not store:
        return artifact
    target = output_dir / relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        target.parent.chmod(0o700)
    except OSError:
        pass
    target.write_text(content, encoding="utf-8")
    try:
        target.chmod(0o600)
    except OSError:
        pass
    artifact["relative_path"] = relative_path.as_posix()
    return artifact


def _run_process(
    command: list[str],
    *,
    cwd: Path,
    environment: Mapping[str, str],
    timeout_seconds: float,
    input_text: str | None,
) -> tuple[dict[str, object], str, str]:
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            env=dict(environment),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            input=input_text,
            timeout=timeout_seconds,
            check=False,
            shell=False,
        )
        status = "succeeded" if completed.returncode == 0 else "failed"
        metadata = {
            "status": status,
            "returncode": completed.returncode,
            "error": None if status == "succeeded" else "nonzero_exit",
        }
        return metadata, completed.stdout, completed.stderr
    except subprocess.TimeoutExpired as error:
        stdout = error.stdout or ""
        stderr = error.stderr or ""
        if isinstance(stdout, bytes):
            stdout = stdout.decode("utf-8", errors="replace")
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", errors="replace")
        return (
            {
                "status": "failed",
                "returncode": None,
                "error": "timeout",
            },
            stdout,
            stderr,
        )
    except FileNotFoundError:
        return (
            {
                "status": "failed",
                "returncode": None,
                "error": "command_not_found",
            },
            "",
            "",
        )
    except OSError:
        return (
            {
                "status": "failed",
                "returncode": None,
                "error": "process_error",
            },
            "",
            "",
        )


def _duration_ms(started: float) -> int:
    return max(0, round((time.perf_counter() - started) * 1000))


def _materialize_mcp_config(
    condition: dict[str, Any],
    *,
    repo: Path,
    harness_root: Path,
    state_dir: Path,
    output_dir: Path,
) -> dict[str, object] | None:
    mcp_config = condition["mcp_config"]
    if mcp_config is None:
        return None
    replacements = {
        "repo": str(repo),
        "state": str(state_dir),
        "prompt": "",
        "harness": str(harness_root),
    }
    materialized = _render_json_value(mcp_config, replacements)
    content = json.dumps(materialized, indent=2, sort_keys=True) + "\n"
    relative_path = Path("state") / condition["id"] / "mcp.json"
    return _write_text_artifact(output_dir, relative_path, content, "mcp_config")


def _environment(
    condition: dict[str, Any], replacements: Mapping[str, str], phase: str
) -> dict[str, str]:
    inherited_names = condition[f"{phase}_inherit_environment"]
    environment = {
        name: os.environ[name]
        for name in _MINIMUM_ENVIRONMENT_NAMES.union(inherited_names)
        if name in os.environ
    }
    environment.update(
        {
            key: _render_string(value, replacements)
            for key, value in condition["environment"].items()
        }
    )
    return environment


def _run_evaluation(
    *,
    tasks_path: str | Path,
    conditions_path: str | Path,
    repo: str | Path,
    output_dir: str | Path,
    data_classification: str,
    harness_root: str | Path = ".",
    seed: int = 0,
    repetitions: int = 1,
    selected_conditions: Sequence[str] | None = None,
    security_evidence_id: str | None = None,
    store_raw_artifacts: bool = False,
    repo_is_disposable_copy: bool = False,
    _state_cleanup: _StateCleanup,
) -> dict[str, object]:
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise EvaluationConfigError("seed must be an integer")
    if data_classification not in _DATA_CLASSIFICATIONS:
        raise EvaluationConfigError(
            "data_classification must be public-fixture or company-source"
        )
    if data_classification == "company-source":
        raise EvaluationConfigError("company-source is disabled in this release")
    if security_evidence_id is not None and (
        not isinstance(security_evidence_id, str) or not security_evidence_id.strip()
    ):
        raise EvaluationConfigError("security_evidence_id must be a non-empty string")
    if security_evidence_id is not None:
        raise EvaluationConfigError(
            "security_evidence_id is reserved for a future approved release"
        )
    if (
        isinstance(repetitions, bool)
        or not isinstance(repetitions, int)
        or repetitions < 1
    ):
        raise EvaluationConfigError("repetitions must be a positive integer")
    repo_path = Path(repo).expanduser().resolve()
    if not repo_path.is_dir():
        raise EvaluationConfigError("repo must be an existing directory")
    harness_path = Path(harness_root).expanduser().resolve()
    if not harness_path.is_dir():
        raise EvaluationConfigError("harness_root must be an existing directory")
    destination = Path(output_dir).expanduser().resolve()

    tasks_document, tasks_sha256 = _load_json(Path(tasks_path), "task suite")
    conditions_document, conditions_sha256 = _load_json(
        Path(conditions_path), "conditions"
    )
    tasks = _validate_tasks(tasks_document)
    conditions = _validate_conditions(conditions_document)
    if selected_conditions is not None:
        selected = list(selected_conditions)
        if len(selected) != len(set(selected)):
            raise EvaluationConfigError("selected condition ids must be unique")
        unknown = set(selected) - {condition["id"] for condition in conditions}
        if unknown:
            raise EvaluationConfigError(
                "selected condition is absent from configuration"
            )
        wanted = set(selected)
        conditions = [
            condition for condition in conditions if condition["id"] in wanted
        ]
    if not conditions:
        raise EvaluationConfigError("at least one condition must be selected")
    prohibited_conditions = [
        condition["id"]
        for condition in conditions
        if data_classification not in condition["allowed_data_classifications"]
    ]
    if prohibited_conditions:
        raise EvaluationConfigError(
            "selected condition is not approved for the data classification"
        )
    if (
        any(condition["id"] == "graphify-native" for condition in conditions)
        and not repo_is_disposable_copy
    ):
        raise EvaluationConfigError(
            "graphify-native requires an explicitly disposable repository copy"
        )
    if store_raw_artifacts and (
        destination.is_relative_to(repo_path)
        or destination.is_relative_to(harness_path)
    ):
        raise EvaluationConfigError(
            "stored raw artifacts require an output directory outside repo and harness"
        )
    if destination.exists():
        if not destination.is_dir() or any(destination.iterdir()):
            raise EvaluationConfigError(
                "output_dir must not exist or must be an empty directory"
            )
    destination.mkdir(parents=True, exist_ok=True)
    _state_cleanup.arm(destination / "state")
    try:
        destination.chmod(0o700)
    except OSError:
        pass

    artifacts: list[dict[str, object]] = []
    preparations: list[dict[str, object]] = []
    preparation_status: dict[str, str] = {}
    for condition in conditions:
        state_dir = (destination / "state" / condition["id"]).resolve()
        state_dir.mkdir(parents=True, exist_ok=True)
        mcp_artifact = _materialize_mcp_config(
            condition,
            repo=repo_path,
            harness_root=harness_path,
            state_dir=state_dir,
            output_dir=destination,
        )
        if mcp_artifact is not None:
            artifacts.append(mcp_artifact)
        prepare_commands = condition["prepare_commands"]
        if not prepare_commands:
            preparation_status[condition["id"]] = "not_required"
            preparations.append(
                {
                    "condition": condition["id"],
                    "status": "not_required",
                    "returncode": None,
                    "error": None,
                    "duration_ms": 0,
                    "artifacts": ([mcp_artifact] if mcp_artifact else []),
                }
            )
            continue
        preparation_status[condition["id"]] = "succeeded"
        for prepare_index, prepare_command in enumerate(prepare_commands):
            replacements = {
                "repo": str(repo_path),
                "state": str(state_dir),
                "prompt": "",
                "harness": str(harness_path),
            }
            rendered_prepare = render_command(prepare_command, replacements)
            started = time.perf_counter()
            process, stdout, stderr = _run_process(
                rendered_prepare,
                cwd=repo_path,
                environment=_environment(condition, replacements, "prepare"),
                timeout_seconds=condition["timeout_seconds"],
                input_text=None,
            )
            relative_base = Path("raw") / condition["id"] / f"prepare-{prepare_index}"
            prepare_artifacts = [
                _write_text_artifact(
                    destination,
                    relative_base / "stdout.txt",
                    stdout,
                    "stdout",
                    store=store_raw_artifacts,
                ),
                _write_text_artifact(
                    destination,
                    relative_base / "stderr.txt",
                    stderr,
                    "stderr",
                    store=store_raw_artifacts,
                ),
            ]
            artifacts.extend(prepare_artifacts)
            preparation_status[condition["id"]] = str(process["status"])
            preparations.append(
                {
                    "condition": condition["id"],
                    "step": prepare_index,
                    **process,
                    "duration_ms": _duration_ms(started),
                    "artifacts": (
                        [mcp_artifact]
                        if mcp_artifact is not None and prepare_index == 0
                        else []
                    )
                    + prepare_artifacts,
                }
            )
            if process["status"] != "succeeded":
                break

    schedule = [
        (repetition, task, condition)
        for repetition in range(repetitions)
        for task in tasks
        for condition in conditions
    ]
    random.Random(seed).shuffle(schedule)
    runs: list[dict[str, object]] = []
    for repetition, task, condition in schedule:
        state_dir = (destination / "state" / condition["id"]).resolve()
        common = {
            "condition": condition["id"],
            "task": task["id"],
            "prompt_sha256": _sha256_text(task["prompt"]),
            "seed": seed,
            "repetition": repetition,
        }
        if preparation_status[condition["id"]] == "failed":
            runs.append(
                {
                    **common,
                    "status": "blocked",
                    "returncode": None,
                    "error": "prepare_failed",
                    "duration_ms": 0,
                    **_null_metrics(),
                    "artifacts": [],
                }
            )
            continue
        replacements = {
            "repo": str(repo_path),
            "state": str(state_dir),
            "prompt": task["prompt"],
            "harness": str(harness_path),
        }
        command = render_command(condition["command"], replacements)
        started = time.perf_counter()
        process, stdout, stderr = _run_process(
            command,
            cwd=repo_path,
            environment=_environment(condition, replacements, "command"),
            timeout_seconds=task.get("timeout_seconds", condition["timeout_seconds"]),
            input_text=task["prompt"],
        )
        relative_base = (
            Path("raw") / condition["id"] / task["id"] / f"repetition-{repetition}"
        )
        run_artifacts = [
            _write_text_artifact(
                destination,
                relative_base / "stdout.txt",
                stdout,
                "stdout",
                store=store_raw_artifacts,
            ),
            _write_text_artifact(
                destination,
                relative_base / "stderr.txt",
                stderr,
                "stderr",
                store=store_raw_artifacts,
            ),
        ]
        artifacts.extend(run_artifacts)
        runs.append(
            {
                **common,
                **process,
                "duration_ms": _duration_ms(started),
                **normalize_claude_output(stdout),
                "artifacts": run_artifacts,
            }
        )

    state_cleanup_status = _state_cleanup.cleanup()
    for artifact in artifacts:
        if artifact["kind"] == "mcp_config":
            artifact["stored"] = False
            artifact.pop("relative_path", None)

    by_condition = {}
    for condition in conditions:
        condition_runs = [run for run in runs if run["condition"] == condition["id"]]
        succeeded = sum(run["status"] == "succeeded" for run in condition_runs)
        by_condition[condition["id"]] = {
            "total_runs": len(condition_runs),
            "succeeded": succeeded,
            "failed": len(condition_runs) - succeeded,
        }
    succeeded = sum(run["status"] == "succeeded" for run in runs)
    failed = len(runs) - succeeded
    status = (
        "completed"
        if failed == 0 and state_cleanup_status == "succeeded"
        else "completed_with_failures"
    )
    result: dict[str, object] = {
        "schema_version": 1,
        "status": status,
        "evaluation": {
            "seed": seed,
            "repetitions": repetitions,
            "conditions": [condition["id"] for condition in conditions],
            "condition_data_policies": {
                condition["id"]: condition["allowed_data_classifications"]
                for condition in conditions
            },
            "repo_path_sha256": _sha256_text(str(repo_path)),
            "harness_path_sha256": _sha256_text(str(harness_path)),
            "data_classification": data_classification,
            "security_evidence_sha256": None,
            "repo_is_disposable_copy": repo_is_disposable_copy,
            "store_raw_artifacts": store_raw_artifacts,
            "environment_policy": {
                condition["id"]: {
                    "minimum_environment_names": sorted(_MINIMUM_ENVIRONMENT_NAMES),
                    "explicit_environment_names": sorted(condition["environment"]),
                    "prepare_inherit_environment": condition[
                        "prepare_inherit_environment"
                    ],
                    "command_inherit_environment": condition[
                        "command_inherit_environment"
                    ],
                }
                for condition in conditions
            },
            "task_suite_sha256": tasks_sha256,
            "conditions_sha256": conditions_sha256,
        },
        "summary": {
            "total_runs": len(runs),
            "succeeded": succeeded,
            "failed": failed,
            "state_cleanup": state_cleanup_status,
            "by_condition": by_condition,
        },
        "next_actions": (
            (
                [
                    "Inspect failed run artifacts in the secured output directory.",
                    "Re-run failed task and condition pairs before comparing "
                    "conditions.",
                ]
                if store_raw_artifacts
                else [
                    "Review hashed failure metadata; raw output was not stored.",
                    "If the data policy permits it, re-run failed pairs with "
                    "--store-raw-artifacts and an approved secured output directory.",
                ]
            )
            if failed
            else [
                "Compare quality review results with normalized usage, cost, "
                "and duration."
            ]
        ),
        "artifacts": artifacts,
        "preparations": preparations,
        "runs": runs,
    }
    result_path = destination / "result.json"
    result_path.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    try:
        result_path.chmod(0o600)
    except OSError:
        pass
    return result


def run_evaluation(
    *,
    tasks_path: str | Path,
    conditions_path: str | Path,
    repo: str | Path,
    output_dir: str | Path,
    data_classification: str,
    harness_root: str | Path = ".",
    seed: int = 0,
    repetitions: int = 1,
    selected_conditions: Sequence[str] | None = None,
    security_evidence_id: str | None = None,
    store_raw_artifacts: bool = False,
    repo_is_disposable_copy: bool = False,
) -> dict[str, object]:
    """Run all selected condition/task combinations and persist a safe summary."""

    state_cleanup = _StateCleanup()
    try:
        return _run_evaluation(
            tasks_path=tasks_path,
            conditions_path=conditions_path,
            repo=repo,
            output_dir=output_dir,
            data_classification=data_classification,
            harness_root=harness_root,
            seed=seed,
            repetitions=repetitions,
            selected_conditions=selected_conditions,
            security_evidence_id=security_evidence_id,
            store_raw_artifacts=store_raw_artifacts,
            repo_is_disposable_copy=repo_is_disposable_copy,
            _state_cleanup=state_cleanup,
        )
    finally:
        state_cleanup.cleanup()


def run_evaluation_cli(args: list[str]) -> int:
    """CLI adapter intended for delegation from the repository's root command."""

    parser = argparse.ArgumentParser(
        prog="codegraph-harness evaluate",
        description=(
            "Run a comparison without downloading vendors. This runner does not "
            "create or prove OS/container/network isolation."
        ),
        epilog=(
            "company-source is disabled in this release; --security-evidence-id is "
            "reserved for a future approved command policy. Raw output is not stored "
            "unless --store-raw-artifacts is explicitly provided."
        ),
    )
    parser.add_argument("--tasks", required=True)
    parser.add_argument("--conditions", required=True)
    parser.add_argument("--repo", default=".")
    parser.add_argument("--harness-root", default=".")
    parser.add_argument("--output-dir", default="evaluation-results")
    parser.add_argument(
        "--data-classification",
        required=True,
        choices=sorted(_DATA_CLASSIFICATIONS),
    )
    parser.add_argument(
        "--security-evidence-id",
        help="reserved; company-source is disabled in this release",
    )
    parser.add_argument("--store-raw-artifacts", action="store_true")
    parser.add_argument("--repo-is-disposable-copy", action="store_true")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--repetitions", type=int, default=1)
    parser.add_argument(
        "--condition",
        action="append",
        choices=sorted(SUPPORTED_CONDITIONS),
        dest="selected_conditions",
    )
    parsed = parser.parse_args(args)
    try:
        result = run_evaluation(
            tasks_path=parsed.tasks,
            conditions_path=parsed.conditions,
            repo=parsed.repo,
            harness_root=parsed.harness_root,
            output_dir=parsed.output_dir,
            data_classification=parsed.data_classification,
            seed=parsed.seed,
            repetitions=parsed.repetitions,
            selected_conditions=parsed.selected_conditions,
            security_evidence_id=parsed.security_evidence_id,
            store_raw_artifacts=parsed.store_raw_artifacts,
            repo_is_disposable_copy=parsed.repo_is_disposable_copy,
        )
    except EvaluationConfigError as error:
        print(f"evaluation configuration error: {error}", file=sys.stderr)
        return 2
    response = {
        key: result[key] for key in ("status", "summary", "next_actions", "artifacts")
    }
    print(json.dumps(response))
    return 0 if result["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(run_evaluation_cli(sys.argv[1:]))
