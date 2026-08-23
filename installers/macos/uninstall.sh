#!/usr/bin/env bash
set -euo pipefail

DATA_ROOT="${CODEGRAPH_DATA_ROOT:-${HOME}/Library/Application Support/CompanyCodegraph}"
STATE_ROOT="${CODEGRAPH_STATE_ROOT:-${DATA_ROOT}/state}"
PURGE_GRAPH_STATE=0

usage() {
  printf '%s\n' "Usage: ./uninstall.sh [--purge-graph-state] [--data-root PATH] [--state-root PATH]"
}

fail() {
  printf 'ERROR: %s\n' "$1" >&2
  exit 1
}

sha256_file() {
  shasum -a 256 "$1" | awk '{print $1}'
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --purge-graph-state) PURGE_GRAPH_STATE=1 ;;
    --data-root)
      [ "$#" -ge 2 ] || fail "--data-root requires a path"
      DATA_ROOT="$2"
      shift
      ;;
    --state-root)
      [ "$#" -ge 2 ] || fail "--state-root requires a path"
      STATE_ROOT="$2"
      shift
      ;;
    -h|--help) usage; exit 0 ;;
    *) fail "Unknown option: $1" ;;
  esac
  shift
done

for configured_root in "$DATA_ROOT" "$STATE_ROOT"; do
  case "$configured_root" in
    /*) ;;
    *) fail "Uninstaller paths must be absolute: ${configured_root}" ;;
  esac
done
[ "$DATA_ROOT" != "/" ] && [ "$DATA_ROOT" != "$HOME" ] || fail "Unsafe data root"
[ "$STATE_ROOT" != "/" ] && [ "$STATE_ROOT" != "$HOME" ] || fail "Unsafe state root"

CURRENT_ROOT="${STATE_ROOT}/current"
[ -d "$CURRENT_ROOT" ] || fail "No installation receipt found at ${CURRENT_ROOT}"
for name in rule_target rule_installed_sha256 codex_skill_target codex_skill_installed_sha256 plugin_id plugin_installed marketplace_added runtime_installed claude_mcp_registered codex_mcp_registered; do
  [ -f "${CURRENT_ROOT}/${name}" ] || fail "Installation receipt is incomplete: ${name}"
done

WARNING=0
PRESERVE_RUNTIME=0

remove_registration() {
  client="$1"
  name="$2"
  registered_name="$3"
  hash_name="$4"
  [ "$(cat "${CURRENT_ROOT}/${registered_name}")" = "1" ] || return 0
  if ! command -v "$client" >/dev/null 2>&1; then
    WARNING=1
    PRESERVE_RUNTIME=1
    printf 'WARNING: %s was not found; MCP registration was preserved\n' "$client" >&2
    return 0
  fi
  if [ "$client" = "claude" ]; then
    output="$(claude mcp get "$name" 2>/dev/null)" || {
      WARNING=1
      PRESERVE_RUNTIME=1
      printf 'WARNING: Claude MCP registration could not be verified\n' >&2
      return 0
    }
  else
    output="$(codex mcp get "$name" --json 2>/dev/null)" || {
      WARNING=1
      PRESERVE_RUNTIME=1
      printf 'WARNING: Codex MCP registration could not be verified\n' >&2
      return 0
    }
  fi
  current_hash="$(printf '%s' "$output" | shasum -a 256 | awk '{print $1}')"
  if [ ! -f "${CURRENT_ROOT}/${hash_name}" ] || [ "$(cat "${CURRENT_ROOT}/${hash_name}")" != "$current_hash" ]; then
    WARNING=1
    PRESERVE_RUNTIME=1
    printf 'WARNING: Preserved user-modified MCP registration: %s\n' "$name" >&2
    return 0
  fi
  if [ "$client" = "claude" ]; then
    claude mcp remove --scope user "$name" || {
      WARNING=1
      PRESERVE_RUNTIME=1
    }
  else
    codex mcp remove "$name" || {
      WARNING=1
      PRESERVE_RUNTIME=1
    }
  fi
}

remove_registration claude company-codegraph claude_mcp_registered claude_mcp_sha256
remove_registration codex company_codegraph codex_mcp_registered codex_mcp_sha256

if [ "$(cat "${CURRENT_ROOT}/plugin_installed")" = "1" ] && command -v claude >/dev/null 2>&1; then
  claude plugin uninstall "$(cat "${CURRENT_ROOT}/plugin_id")" --scope user --yes || WARNING=1
elif [ "$(cat "${CURRENT_ROOT}/plugin_installed")" = "1" ]; then
  WARNING=1
  printf '%s\n' 'WARNING: Claude Code was not found; plugin removal could not be verified' >&2
fi
if [ "$(cat "${CURRENT_ROOT}/marketplace_added")" = "1" ] && command -v claude >/dev/null 2>&1; then
  claude plugin marketplace remove codegraph-harness --scope user || WARNING=1
fi

preserve_or_remove() {
  target_name="$1"
  hash_name="$2"
  label="$3"
  target="$(cat "${CURRENT_ROOT}/${target_name}")"
  [ -f "$target" ] || return 0
  if [ "$(sha256_file "$target")" = "$(cat "${CURRENT_ROOT}/${hash_name}")" ]; then
    rm -f "$target"
  else
    WARNING=1
    printf 'WARNING: Preserved user-modified %s: %s\n' "$label" "$target" >&2
  fi
}

preserve_or_remove rule_target rule_installed_sha256 "Rule"
preserve_or_remove codex_skill_target codex_skill_installed_sha256 "Codex skill"

if [ "$(cat "${CURRENT_ROOT}/runtime_installed")" = "1" ]; then
  for name in runtime_root gateway_path backend_path gateway_sha256 backend_sha256; do
    [ -f "${CURRENT_ROOT}/${name}" ] || fail "Installation receipt is incomplete: ${name}"
  done
  runtime_root="$(cat "${CURRENT_ROOT}/runtime_root")"
  gateway="$(cat "${CURRENT_ROOT}/gateway_path")"
  backend="$(cat "${CURRENT_ROOT}/backend_path")"
  if [ "$PRESERVE_RUNTIME" -eq 1 ]; then
    WARNING=1
    printf 'WARNING: Preserved runtime because an MCP registration remains\n' >&2
  elif [ -f "$gateway" ] && [ -f "$backend" ] && \
     [ "$(sha256_file "$gateway")" = "$(cat "${CURRENT_ROOT}/gateway_sha256")" ] && \
     [ "$(sha256_file "$backend")" = "$(cat "${CURRENT_ROOT}/backend_sha256")" ]; then
    rm -f "$gateway" "$backend"
    rmdir "$(dirname "$gateway")" 2>/dev/null || true
    rmdir "$runtime_root" 2>/dev/null || true
  elif [ -e "$runtime_root" ]; then
    WARNING=1
    printf 'WARNING: Preserved user-modified runtime: %s\n' "$runtime_root" >&2
  fi
fi

for name in version install_root rule_target rule_installed_sha256 codex_skill_target codex_skill_installed_sha256 plugin_id plugin_installed marketplace_added runtime_installed runtime_platform runtime_arch runtime_root gateway_path backend_path gateway_sha256 backend_sha256 claude_gateway_sha256 claude_backend_sha256 codex_gateway_sha256 codex_backend_sha256 config_path config_sha256 git_binary git_sha256 allowed_root claude_mcp_registered claude_mcp_sha256 codex_mcp_registered codex_mcp_sha256; do
  rm -f "${CURRENT_ROOT}/${name}"
done
rmdir "$CURRENT_ROOT" 2>/dev/null || true

if [ "$PURGE_GRAPH_STATE" -eq 1 ]; then
  GRAPH_STATE_ROOT="${DATA_ROOT}/graph-state"
  [ ! -L "$GRAPH_STATE_ROOT" ] || fail "Graph state root must not be a symlink"
  [ ! -e "$GRAPH_STATE_ROOT" ] || rm -rf -- "$GRAPH_STATE_ROOT"
fi

if [ "$WARNING" -eq 1 ]; then
  printf '%s\n' '{"status":"warning","summary":"Uninstall completed with preserved user-modified or unverifiable items","next_actions":["Review warnings and remove retained graph state if required"],"artifacts":[]}'
else
  if [ "$PURGE_GRAPH_STATE" -eq 1 ]; then
    printf '%s\n' '{"status":"success","summary":"Codegraph harness and derived graph state uninstalled","next_actions":[],"artifacts":[]}'
  else
    printf '%s\n' '{"status":"success","summary":"Codegraph harness uninstalled; derived graph state retained","next_actions":["Delete the retained graph-state directory through the approved internal procedure if policy requires it"],"artifacts":[]}'
  fi
fi
