#!/usr/bin/env bash
set -euo pipefail

DATA_ROOT="${CODEGRAPH_DATA_ROOT:-${HOME}/Library/Application Support/ClaudeCodeCodegraphHarness}"
STATE_ROOT="${CODEGRAPH_STATE_ROOT:-${DATA_ROOT}/state}"

usage() {
  printf '%s\n' "Usage: ./uninstall.sh [--data-root PATH] [--state-root PATH]"
}

fail() {
  printf 'ERROR: %s\n' "$1" >&2
  exit 1
}

while [ "$#" -gt 0 ]; do
  case "$1" in
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

CURRENT_ROOT="${STATE_ROOT}/current"

[ -d "$CURRENT_ROOT" ] || fail "No installation receipt found at ${CURRENT_ROOT}"
for name in rule_target rule_backup rule_installed_sha256 plugin_id plugin_skipped; do
  [ -f "${CURRENT_ROOT}/${name}" ] || fail "Installation receipt is incomplete: ${name}"
done

RULE_TARGET="$(cat "${CURRENT_ROOT}/rule_target")"
RULE_BACKUP="$(cat "${CURRENT_ROOT}/rule_backup")"
RULE_INSTALLED_SHA="$(cat "${CURRENT_ROOT}/rule_installed_sha256")"
PLUGIN_ID="$(cat "${CURRENT_ROOT}/plugin_id")"
PLUGIN_SKIPPED="$(cat "${CURRENT_ROOT}/plugin_skipped")"

PLUGIN_WARNING=0
if [ "$PLUGIN_SKIPPED" = "0" ] && command -v claude >/dev/null 2>&1; then
  claude plugin uninstall "$PLUGIN_ID" --scope user --yes || PLUGIN_WARNING=1
  claude plugin marketplace remove codegraph-harness --scope user || PLUGIN_WARNING=1
elif [ "$PLUGIN_SKIPPED" = "0" ]; then
  PLUGIN_WARNING=1
  printf '%s\n' 'WARNING: Claude Code was not found; plugin removal could not be verified' >&2
fi

PRESERVED_RULE=0
if [ -f "$RULE_TARGET" ]; then
  current_hash="$(shasum -a 256 "$RULE_TARGET" | awk '{print $1}')"
  if [ "$current_hash" = "$RULE_INSTALLED_SHA" ]; then
    if [ -n "$RULE_BACKUP" ] && [ -f "$RULE_BACKUP" ]; then
      cp "$RULE_BACKUP" "$RULE_TARGET"
    else
      rm -f "$RULE_TARGET"
    fi
  else
    PRESERVED_RULE=1
    printf 'WARNING: Preserved user-modified Rule: %s\n' "$RULE_TARGET" >&2
  fi
fi

rm -f "${CURRENT_ROOT}/version" "${CURRENT_ROOT}/install_root" "${CURRENT_ROOT}/rule_target" \
  "${CURRENT_ROOT}/rule_backup" "${CURRENT_ROOT}/rule_installed_sha256" \
  "${CURRENT_ROOT}/plugin_id" "${CURRENT_ROOT}/plugin_skipped"
rmdir "$CURRENT_ROOT" 2>/dev/null || true

if [ "$PRESERVED_RULE" -eq 1 ] || [ "$PLUGIN_WARNING" -eq 1 ]; then
  printf '{"status":"warning","summary":"Uninstall completed with items requiring review","next_actions":["Verify plugin removal and review any preserved Rule"],"artifacts":["%s"]}\n' "$RULE_TARGET"
else
  printf '%s\n' '{"status":"success","summary":"Codegraph harness uninstalled","next_actions":[],"artifacts":[]}'
fi
