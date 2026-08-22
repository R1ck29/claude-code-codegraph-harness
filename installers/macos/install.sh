#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd -P)"
DRY_RUN=0
SKIP_PLUGIN=0
CLAUDE_CONFIG_ROOT="${CLAUDE_CONFIG_DIR:-${HOME}/.claude}"
DATA_ROOT="${CODEGRAPH_DATA_ROOT:-${HOME}/Library/Application Support/ClaudeCodeCodegraphHarness}"
STATE_ROOT="${CODEGRAPH_STATE_ROOT:-${DATA_ROOT}/state}"

usage() {
  printf '%s\n' "Usage: ./install.sh [--dry-run] [--skip-plugin] [--claude-config-dir PATH] [--data-root PATH] [--state-root PATH]"
}

fail() {
  printf 'ERROR: %s\n' "$1" >&2
  exit 1
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --dry-run) DRY_RUN=1 ;;
    --skip-plugin) SKIP_PLUGIN=1 ;;
    --claude-config-dir)
      [ "$#" -ge 2 ] || fail "--claude-config-dir requires a path"
      CLAUDE_CONFIG_ROOT="$2"
      shift
      ;;
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

if [ "$(uname -s)" != "Darwin" ] && [ "${CODEGRAPH_ALLOW_TEST_OS:-0}" != "1" ]; then
  fail "This entry point supports macOS only"
fi

for required in VERSION SHA256SUMS bundle-manifest.json profile.json install.sh uninstall.sh install.ps1 uninstall.ps1 payload/marketplace/.claude-plugin/marketplace.json payload/marketplace/plugins/codegraph-evaluator/.claude-plugin/plugin.json payload/rules/codegraph-harness.md; do
  [ -e "${SCRIPT_DIR}/${required}" ] || fail "Bundle is missing ${required}"
done

verify_checksums() {
  while IFS='  ' read -r expected relative; do
    [ -n "$expected" ] || continue
    relative="${relative# }"
    case "$relative" in
      /*|../*|*/../*|*/..) fail "Unsafe checksum path: ${relative}" ;;
    esac
    [ -f "${SCRIPT_DIR}/${relative}" ] || fail "Missing checksummed file: ${relative}"
    actual="$(shasum -a 256 "${SCRIPT_DIR}/${relative}" | awk '{print $1}')"
    [ "$actual" = "$expected" ] || fail "Checksum mismatch: ${relative}"
  done < "${SCRIPT_DIR}/SHA256SUMS"
}

verify_checksums

checksum_contains() {
  needle="$1"
  while IFS='  ' read -r _ relative; do
    relative="${relative# }"
    [ "$relative" = "$needle" ] && return 0
  done < "${SCRIPT_DIR}/SHA256SUMS"
  return 1
}

for required in VERSION bundle-manifest.json profile.json install.sh uninstall.sh install.ps1 uninstall.ps1 payload/marketplace/.claude-plugin/marketplace.json payload/marketplace/plugins/codegraph-evaluator/.claude-plugin/plugin.json payload/rules/codegraph-harness.md; do
  checksum_contains "$required" || fail "Mandatory file is not checksummed: ${required}"
done

VERSION="$(tr -d '\r\n' < "${SCRIPT_DIR}/VERSION")"
case "$VERSION" in
  ''|*[!A-Za-z0-9._-]*) fail "Unsafe VERSION value" ;;
esac

INSTALL_ROOT="${DATA_ROOT}/versions/${VERSION}"
CURRENT_ROOT="${STATE_ROOT}/current"
RULE_TARGET="${CLAUDE_CONFIG_ROOT}/rules/codegraph-harness.md"
PLUGIN_ID="codegraph-evaluator@codegraph-harness"
PRIOR_RULE_BACKUP=""
REINSTALL=0

printf 'Plan:\n'
printf '  plugin marketplace: %s\n' "${INSTALL_ROOT}/marketplace"
printf '  plugin: %s\n' "$PLUGIN_ID"
printf '  rule: %s\n' "$RULE_TARGET"
printf '  state: %s\n' "$STATE_ROOT"

if [ "$DRY_RUN" -eq 1 ]; then
  printf '%s\n' '{"status":"success","summary":"Dry run completed; no files changed","next_actions":["Run install.sh without --dry-run"],"artifacts":[]}'
  exit 0
fi

command -v claude >/dev/null 2>&1 || fail "Claude Code executable was not found on PATH"

if [ -f "$RULE_TARGET" ]; then
  if [ ! -f "${CURRENT_ROOT}/rule_installed_sha256" ] || [ ! -f "${CURRENT_ROOT}/rule_target" ]; then
    fail "Rule target already exists and is not owned by this extension: ${RULE_TARGET}"
  fi
  owned_target="$(cat "${CURRENT_ROOT}/rule_target")"
  installed_hash="$(cat "${CURRENT_ROOT}/rule_installed_sha256")"
  current_hash="$(shasum -a 256 "$RULE_TARGET" | awk '{print $1}')"
  if [ "$owned_target" != "$RULE_TARGET" ] || [ "$installed_hash" != "$current_hash" ]; then
    fail "Rule target was changed or is not owned by this extension: ${RULE_TARGET}"
  fi
  PRIOR_RULE_BACKUP="$(cat "${CURRENT_ROOT}/rule_backup")"
  REINSTALL=1
fi

mkdir -p "${DATA_ROOT}/versions" "$STATE_ROOT"
STAGING_ROOT="${DATA_ROOT}/.staging-${VERSION}-$$"
[ ! -e "$STAGING_ROOT" ] || fail "Staging path already exists"
mkdir -p "$STAGING_ROOT"

cleanup_staging() {
  if [ -d "$STAGING_ROOT" ]; then
    rm -rf "$STAGING_ROOT"
  fi
}
trap cleanup_staging EXIT INT TERM

cp -R "${SCRIPT_DIR}/payload/marketplace" "${STAGING_ROOT}/marketplace"
cp "${SCRIPT_DIR}/VERSION" "${STAGING_ROOT}/VERSION"
cp "${SCRIPT_DIR}/bundle-manifest.json" "${STAGING_ROOT}/bundle-manifest.json"

if [ ! -d "$INSTALL_ROOT" ]; then
  mv "$STAGING_ROOT" "$INSTALL_ROOT"
else
  cleanup_staging
fi

ROLLBACK_RULE_PATH=""
if [ "$REINSTALL" -eq 1 ]; then
  BACKUP_ROOT="${STATE_ROOT}/backups/$(date -u +%Y%m%dT%H%M%SZ)"
  mkdir -p "$BACKUP_ROOT"
  ROLLBACK_RULE_PATH="${BACKUP_ROOT}/codegraph-harness.md"
  cp "$RULE_TARGET" "$ROLLBACK_RULE_PATH"
fi

RULE_CREATED=0
PLUGIN_INSTALLED=0
MARKETPLACE_ADDED=0
rollback_partial() {
  status="$?"
  if [ "$status" -ne 0 ]; then
    if [ "$PLUGIN_INSTALLED" -eq 1 ]; then
      claude plugin uninstall "$PLUGIN_ID" --scope user --yes >/dev/null 2>&1 || true
    fi
    if [ "$MARKETPLACE_ADDED" -eq 1 ]; then
      claude plugin marketplace remove codegraph-harness --scope user >/dev/null 2>&1 || true
    fi
    if [ "$RULE_CREATED" -eq 1 ]; then
      if [ -n "$ROLLBACK_RULE_PATH" ] && [ -f "$ROLLBACK_RULE_PATH" ]; then
        cp "$ROLLBACK_RULE_PATH" "$RULE_TARGET"
      else
        rm -f "$RULE_TARGET"
      fi
    fi
  fi
  cleanup_staging
  exit "$status"
}
trap rollback_partial EXIT INT TERM

mkdir -p "$(dirname "$RULE_TARGET")"
cp "${SCRIPT_DIR}/payload/rules/codegraph-harness.md" "$RULE_TARGET"
RULE_CREATED=1

if [ "$SKIP_PLUGIN" -eq 0 ]; then
  claude plugin marketplace add "${INSTALL_ROOT}/marketplace" --scope user
  MARKETPLACE_ADDED=1
  claude plugin install "$PLUGIN_ID" --scope user --yes
  PLUGIN_INSTALLED=1
fi

NEW_RECEIPT_ROOT="${STATE_ROOT}/.current-${VERSION}-$$"
mkdir -p "$NEW_RECEIPT_ROOT"
printf '%s' "$VERSION" > "${NEW_RECEIPT_ROOT}/version"
printf '%s' "$INSTALL_ROOT" > "${NEW_RECEIPT_ROOT}/install_root"
printf '%s' "$RULE_TARGET" > "${NEW_RECEIPT_ROOT}/rule_target"
printf '%s' "$PRIOR_RULE_BACKUP" > "${NEW_RECEIPT_ROOT}/rule_backup"
shasum -a 256 "$RULE_TARGET" | awk '{print $1}' > "${NEW_RECEIPT_ROOT}/rule_installed_sha256"
printf '%s' "$PLUGIN_ID" > "${NEW_RECEIPT_ROOT}/plugin_id"
printf '%s' "$SKIP_PLUGIN" > "${NEW_RECEIPT_ROOT}/plugin_skipped"
if [ -d "$CURRENT_ROOT" ]; then
  rm -f "${CURRENT_ROOT}/version" "${CURRENT_ROOT}/install_root" \
    "${CURRENT_ROOT}/rule_target" "${CURRENT_ROOT}/rule_backup" \
    "${CURRENT_ROOT}/rule_installed_sha256" "${CURRENT_ROOT}/plugin_id" \
    "${CURRENT_ROOT}/plugin_skipped"
  rmdir "$CURRENT_ROOT"
fi
mv "$NEW_RECEIPT_ROOT" "$CURRENT_ROOT"
if [ -n "$ROLLBACK_RULE_PATH" ]; then
  rm -f "$ROLLBACK_RULE_PATH"
  rmdir "$(dirname "$ROLLBACK_RULE_PATH")" 2>/dev/null || true
fi

trap cleanup_staging EXIT INT TERM
printf '{"status":"success","summary":"Codegraph harness installed","next_actions":["Restart Claude Code or run /reload-plugins"],"artifacts":["%s"]}\n' "${CURRENT_ROOT}"
