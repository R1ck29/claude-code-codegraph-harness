#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd -P)"
DRY_RUN=0
SKIP_PLUGIN=0
ADAPTER_ONLY=0
ALLOWED_ROOT="${CODEGRAPH_ALLOWED_ROOT:-}"
CLAUDE_CONFIG_ROOT="${CLAUDE_CONFIG_DIR:-${HOME}/.claude}"
CODEX_SKILL_ROOT="${CODEGRAPH_CODEX_SKILLS_ROOT:-${HOME}/.agents/skills}"
DATA_ROOT="${CODEGRAPH_DATA_ROOT:-${HOME}/Library/Application Support/CompanyCodegraph}"
STATE_ROOT="${CODEGRAPH_STATE_ROOT:-${DATA_ROOT}/state}"

usage() {
  printf '%s\n' "Usage: ./install.sh [--dry-run] [--adapter-only] [--skip-plugin] [--allowed-root PATH] [--claude-config-dir PATH] [--codex-skill-root PATH] [--data-root PATH] [--state-root PATH]"
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
    --dry-run) DRY_RUN=1 ;;
    --adapter-only) ADAPTER_ONLY=1 ;;
    --skip-plugin) SKIP_PLUGIN=1 ;;
    --allowed-root)
      [ "$#" -ge 2 ] || fail "--allowed-root requires a path"
      ALLOWED_ROOT="$2"
      shift
      ;;
    --claude-config-dir)
      [ "$#" -ge 2 ] || fail "--claude-config-dir requires a path"
      CLAUDE_CONFIG_ROOT="$2"
      shift
      ;;
    --codex-skill-root)
      [ "$#" -ge 2 ] || fail "--codex-skill-root requires a path"
      CODEX_SKILL_ROOT="$2"
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

for configured_root in "$CLAUDE_CONFIG_ROOT" "$CODEX_SKILL_ROOT" "$DATA_ROOT" "$STATE_ROOT"; do
  case "$configured_root" in
    /*) ;;
    *) fail "Installer paths must be absolute: ${configured_root}" ;;
  esac
done
if [ "$DATA_ROOT" = "/" ] || [ "$DATA_ROOT" = "$HOME" ]; then
  fail "Unsafe data root"
fi
if [ "$STATE_ROOT" = "/" ] || [ "$STATE_ROOT" = "$HOME" ]; then
  fail "Unsafe state root"
fi
if [ -n "$ALLOWED_ROOT" ]; then
  case "$ALLOWED_ROOT" in
    /*) ;;
    *) fail "--allowed-root must be an absolute path" ;;
  esac
  [ ! -L "$ALLOWED_ROOT" ] || fail "--allowed-root must not be a symlink"
  [ -d "$ALLOWED_ROOT" ] || fail "--allowed-root must be an existing directory"
  ALLOWED_ROOT="$(cd "$ALLOWED_ROOT" && pwd -P)"
  if [ "$ALLOWED_ROOT" = "/" ] || [ "$ALLOWED_ROOT" = "$HOME" ]; then
    fail "Unsafe allowed root"
  fi
fi

if [ "$(uname -s)" != "Darwin" ] && [ "${CODEGRAPH_ALLOW_TEST_OS:-0}" != "1" ]; then
  fail "This entry point supports macOS only"
fi

required_assets="VERSION bundle-manifest.json profile.json install.sh uninstall.sh install.ps1 uninstall.ps1 payload/marketplace/.claude-plugin/marketplace.json payload/marketplace/plugins/codegraph-evaluator/.claude-plugin/plugin.json payload/rules/codegraph-harness.md payload/clients/routing-policy.json payload/codex/.codex-plugin/plugin.json payload/codex/skills/company-codegraph/SKILL.md payload/codex/config.example.toml"
for required in SHA256SUMS $required_assets; do
  [ ! -L "${SCRIPT_DIR}/${required}" ] || fail "Bundle file must not be a symlink: ${required}"
  [ -f "${SCRIPT_DIR}/${required}" ] || fail "Bundle is missing ${required}"
done

verify_checksums() {
  while IFS= read -r line || [ -n "$line" ]; do
    [ -n "$line" ] || continue
    expected="${line%%  *}"
    relative="${line#*  }"
    [ "$relative" != "$line" ] || fail "Invalid SHA256SUMS line"
    case "$expected" in
      *[!0-9a-f]*|'') fail "Invalid SHA256SUMS digest" ;;
    esac
    [ "${#expected}" -eq 64 ] || fail "Invalid SHA256SUMS digest"
    case "$relative" in
      /*|../*|*/../*|*/..|*\\*) fail "Unsafe checksum path: ${relative}" ;;
    esac
    [ ! -L "${SCRIPT_DIR}/${relative}" ] || fail "Bundle file must not be a symlink: ${relative}"
    [ -f "${SCRIPT_DIR}/${relative}" ] || fail "Missing checksummed file: ${relative}"
    actual="$(sha256_file "${SCRIPT_DIR}/${relative}")"
    [ "$actual" = "$expected" ] || fail "Checksum mismatch: ${relative}"
  done < "${SCRIPT_DIR}/SHA256SUMS"
}

checksum_contains() {
  needle="$1"
  while IFS= read -r line || [ -n "$line" ]; do
    relative="${line#*  }"
    [ "$relative" = "$needle" ] && return 0
  done < "${SCRIPT_DIR}/SHA256SUMS"
  return 1
}

verify_complete_file_set() {
  while IFS= read -r -d '' candidate; do
    relative="${candidate#"${SCRIPT_DIR}/"}"
    [ ! -L "$candidate" ] || fail "Bundle entry must not be a symlink: ${relative}"
    if [ -f "$candidate" ]; then
      [ "$relative" = "SHA256SUMS" ] || checksum_contains "$relative" || fail "Unchecksummed bundle file: ${relative}"
    elif [ ! -d "$candidate" ]; then
      fail "Bundle entry must be a regular file or directory: ${relative}"
    fi
  done < <(find "$SCRIPT_DIR" -mindepth 1 -print0)
}

verify_checksums
for required in $required_assets; do
  checksum_contains "$required" || fail "Mandatory file is not checksummed: ${required}"
done
verify_complete_file_set

VERSION="$(tr -d '\r\n' < "${SCRIPT_DIR}/VERSION")"
case "$VERSION" in
  ''|*[!A-Za-z0-9._-]*) fail "Unsafe VERSION value" ;;
esac

if [ "${CODEGRAPH_ALLOW_TEST_OS:-0}" = "1" ] && [ -n "${CODEGRAPH_TEST_PLATFORM:-}" ]; then
  PLATFORM="$CODEGRAPH_TEST_PLATFORM"
else
  PLATFORM="macos"
fi
if [ "${CODEGRAPH_ALLOW_TEST_OS:-0}" = "1" ] && [ -n "${CODEGRAPH_TEST_ARCH:-}" ]; then
  RAW_ARCH="$CODEGRAPH_TEST_ARCH"
else
  RAW_ARCH="$(uname -m)"
fi
case "$RAW_ARCH" in
  arm64|aarch64) ARCH="arm64" ;;
  x86_64|amd64) ARCH="x86_64" ;;
  *) fail "Unsupported architecture: ${RAW_ARCH}" ;;
esac
[ "$PLATFORM" = "macos" ] || fail "Unsupported platform: ${PLATFORM}"

INSTALL_ROOT="${DATA_ROOT}/versions/${VERSION}"
CURRENT_ROOT="${STATE_ROOT}/current"
RULE_TARGET="${CLAUDE_CONFIG_ROOT}/rules/codegraph-harness.md"
CODEX_SKILL_TARGET="${CODEX_SKILL_ROOT}/company-codegraph/SKILL.md"
PLUGIN_ID="codegraph-evaluator@codegraph-harness"
CLAUDE_MCP_ID="company-codegraph"
CODEX_MCP_ID="company_codegraph"
RUNTIME_SOURCE_ROOT="${SCRIPT_DIR}/runtime/${PLATFORM}-${ARCH}"
RUNTIME_TARGET_ROOT="${DATA_ROOT}/runtime/${PLATFORM}-${ARCH}"
RUNTIME_INSTALL=0
GATEWAY_SOURCE=""
BACKEND_SOURCE=""
GATEWAY_TARGET=""
BACKEND_TARGET=""
GATEWAY_SHA256=""
BACKEND_SHA256=""
CONFIG_SHA256="$(sha256_file "${SCRIPT_DIR}/payload/clients/routing-policy.json")"
CONFIG_TARGET="${INSTALL_ROOT}/clients/routing-policy.json"
GIT_BINARY=""
GIT_SHA256=""

if [ -f "${SCRIPT_DIR}/runtime/manifest.json" ]; then
  checksum_contains "runtime/manifest.json" || fail "Mandatory file is not checksummed: runtime/manifest.json"
  GATEWAY_SOURCE="${RUNTIME_SOURCE_ROOT}/bin/codegraph-gateway"
  BACKEND_SOURCE="${RUNTIME_SOURCE_ROOT}/bin/codebase-memory-mcp"
  [ -f "$GATEWAY_SOURCE" ] || fail "Bundle has no runtime for ${PLATFORM}/${ARCH}"
  [ -f "$BACKEND_SOURCE" ] || fail "Bundle has no runtime for ${PLATFORM}/${ARCH}"
  gateway_relative="runtime/${PLATFORM}-${ARCH}/bin/codegraph-gateway"
  backend_relative="runtime/${PLATFORM}-${ARCH}/bin/codebase-memory-mcp"
  checksum_contains "$gateway_relative" || fail "Mandatory file is not checksummed: ${gateway_relative}"
  checksum_contains "$backend_relative" || fail "Mandatory file is not checksummed: ${backend_relative}"
  GATEWAY_TARGET="${RUNTIME_TARGET_ROOT}/bin/codegraph-gateway"
  BACKEND_TARGET="${RUNTIME_TARGET_ROOT}/bin/codebase-memory-mcp"
  GATEWAY_SHA256="$(sha256_file "$GATEWAY_SOURCE")"
  BACKEND_SHA256="$(sha256_file "$BACKEND_SOURCE")"
  if [ "$ADAPTER_ONLY" -eq 0 ]; then
    [ -n "$ALLOWED_ROOT" ] || fail "--allowed-root is required for runtime installation"
    GIT_COMMAND="$(command -v git || true)"
    [ -n "$GIT_COMMAND" ] || fail "A managed Git executable is required for runtime installation"
    GIT_BINARY="$(cd "$(dirname "$GIT_COMMAND")" && pwd -P)/$(basename "$GIT_COMMAND")"
    [ -f "$GIT_BINARY" ] || fail "Managed Git path is not a regular file"
    GIT_SHA256="$(sha256_file "$GIT_BINARY")"
    RUNTIME_INSTALL=1
  fi
fi

printf 'Plan:\n'
printf '  Claude plugin marketplace: %s\n' "${INSTALL_ROOT}/marketplace"
printf '  Claude Rule: %s\n' "$RULE_TARGET"
printf '  Codex skill: %s\n' "$CODEX_SKILL_TARGET"
printf '  selected runtime: %s/%s (%s)\n' "$PLATFORM" "$ARCH" "$RUNTIME_INSTALL"
printf '  state: %s\n' "$STATE_ROOT"

if [ "$DRY_RUN" -eq 1 ]; then
  printf '%s\n' '{"status":"success","summary":"Dry run completed; no files changed","next_actions":["Run install.sh without --dry-run"],"artifacts":[]}'
  exit 0
fi

REINSTALL=0
if [ -d "$CURRENT_ROOT" ]; then
  REINSTALL=1
  for receipt_name in rule_target rule_installed_sha256 codex_skill_target codex_skill_installed_sha256 runtime_installed config_path config_sha256 claude_mcp_registered codex_mcp_registered; do
    [ -f "${CURRENT_ROOT}/${receipt_name}" ] || fail "Installation receipt is incomplete: ${receipt_name}"
  done
fi

verify_owned_file() {
  target="$1"
  receipt_target_name="$2"
  receipt_hash_name="$3"
  label="$4"
  [ ! -L "$target" ] || fail "${label} target must not be a symlink: ${target}"
  if [ ! -f "$target" ]; then
    [ "$REINSTALL" -eq 0 ] || fail "Owned ${label} is missing: ${target}"
    return
  fi
  [ "$REINSTALL" -eq 1 ] || fail "${label} target exists and is not owned by this extension: ${target}"
  [ "$(cat "${CURRENT_ROOT}/${receipt_target_name}")" = "$target" ] || fail "${label} target is not owned by this extension: ${target}"
  [ "$(cat "${CURRENT_ROOT}/${receipt_hash_name}")" = "$(sha256_file "$target")" ] || fail "${label} target was changed: ${target}"
}

verify_owned_file "$RULE_TARGET" rule_target rule_installed_sha256 "Rule"
verify_owned_file "$CODEX_SKILL_TARGET" codex_skill_target codex_skill_installed_sha256 "Codex skill"

if [ "$RUNTIME_INSTALL" -eq 1 ] && [ -e "$RUNTIME_TARGET_ROOT" ]; then
  [ "$REINSTALL" -eq 1 ] || fail "Runtime target exists and is not owned by this extension: ${RUNTIME_TARGET_ROOT}"
  [ "$(cat "${CURRENT_ROOT}/runtime_installed")" = "1" ] || fail "Runtime target exists and is not owned by this extension: ${RUNTIME_TARGET_ROOT}"
  for receipt_name in gateway_path backend_path gateway_sha256 backend_sha256 runtime_platform runtime_arch git_binary git_sha256; do
    [ -f "${CURRENT_ROOT}/${receipt_name}" ] || fail "Installation receipt is incomplete: ${receipt_name}"
  done
  [ "$(cat "${CURRENT_ROOT}/gateway_path")" = "$GATEWAY_TARGET" ] || fail "Gateway path is not owned by this extension"
  [ "$(cat "${CURRENT_ROOT}/backend_path")" = "$BACKEND_TARGET" ] || fail "Backend path is not owned by this extension"
  if [ ! -f "$GATEWAY_TARGET" ] || [ ! -f "$BACKEND_TARGET" ]; then
    fail "Owned runtime is incomplete"
  fi
  [ "$(cat "${CURRENT_ROOT}/gateway_sha256")" = "$(sha256_file "$GATEWAY_TARGET")" ] || fail "Gateway was changed after installation"
  [ "$(cat "${CURRENT_ROOT}/backend_sha256")" = "$(sha256_file "$BACKEND_TARGET")" ] || fail "Backend was changed after installation"
  [ "$(cat "${CURRENT_ROOT}/git_binary")" = "$GIT_BINARY" ] || fail "Managed Git path changed since installation"
  [ "$(cat "${CURRENT_ROOT}/git_sha256")" = "$GIT_SHA256" ] || fail "Managed Git binary changed since installation"
  [ -f "${CURRENT_ROOT}/allowed_root" ] || fail "Installation receipt is incomplete: allowed_root"
  [ "$(cat "${CURRENT_ROOT}/allowed_root")" = "$ALLOWED_ROOT" ] || fail "Allowed root changed since installation"
fi

registration_output() {
  client="$1"
  name="$2"
  if [ "$client" = "claude" ]; then
    claude mcp get "$name" 2>/dev/null
  else
    codex mcp get "$name" --json 2>/dev/null
  fi
}

registration_hash() {
  output="$(registration_output "$1" "$2")" || return 1
  printf '%s' "$output" | shasum -a 256 | awk '{print $1}'
}

check_registration_collision() {
  client="$1"
  name="$2"
  registered_receipt="$3"
  hash_receipt="$4"
  command -v "$client" >/dev/null 2>&1 || return 0
  current_hash="$(registration_hash "$client" "$name")" || return 0
  if [ "$REINSTALL" -ne 1 ] || [ "$(cat "${CURRENT_ROOT}/${registered_receipt}")" != "1" ]; then
    fail "MCP registration already exists and is not owned: ${name}"
  fi
  [ -f "${CURRENT_ROOT}/${hash_receipt}" ] || fail "Installation receipt is incomplete: ${hash_receipt}"
  [ "$(cat "${CURRENT_ROOT}/${hash_receipt}")" = "$current_hash" ] || fail "Owned MCP registration was changed: ${name}"
}

if [ "$RUNTIME_INSTALL" -eq 1 ]; then
  check_registration_collision claude "$CLAUDE_MCP_ID" claude_mcp_registered claude_mcp_sha256
  check_registration_collision codex "$CODEX_MCP_ID" codex_mcp_registered codex_mcp_sha256
fi

INSTALL_ROOT_CREATED=0
RUNTIME_ROOT_CREATED=0
RULE_WRITTEN=0
SKILL_WRITTEN=0
PLUGIN_INSTALLED=0
MARKETPLACE_ADDED=0
CLAUDE_MCP_REGISTERED=0
CODEX_MCP_REGISTERED=0
CLAUDE_MCP_CREATED=0
CODEX_MCP_CREATED=0
CLAUDE_MCP_SHA256=""
CODEX_MCP_SHA256=""
STAGING_ROOT="${DATA_ROOT}/.staging-${VERSION}-$$"
[ ! -e "$STAGING_ROOT" ] || fail "Staging path already exists"
mkdir -p "$STAGING_ROOT/install/marketplace" "$STAGING_ROOT/install/clients" "$STAGING_ROOT/install/codex"

cleanup_staging() {
  [ ! -d "$STAGING_ROOT" ] || rm -rf "$STAGING_ROOT"
}

rollback_partial() {
  status="$?"
  trap - EXIT INT TERM
  if [ "$status" -ne 0 ]; then
    set +e
    [ "$CODEX_MCP_CREATED" -eq 0 ] || codex mcp remove "$CODEX_MCP_ID" >/dev/null 2>&1
    [ "$CLAUDE_MCP_CREATED" -eq 0 ] || claude mcp remove --scope user "$CLAUDE_MCP_ID" >/dev/null 2>&1
    [ "$PLUGIN_INSTALLED" -eq 0 ] || claude plugin uninstall "$PLUGIN_ID" --scope user --yes >/dev/null 2>&1
    [ "$MARKETPLACE_ADDED" -eq 0 ] || claude plugin marketplace remove codegraph-harness --scope user >/dev/null 2>&1
    if [ "$RULE_WRITTEN" -eq 1 ]; then
      if [ "$REINSTALL" -eq 1 ] && [ -f "$STAGING_ROOT/rollback-rule" ]; then
        cp "$STAGING_ROOT/rollback-rule" "$RULE_TARGET"
      else
        rm -f "$RULE_TARGET"
      fi
    fi
    if [ "$SKILL_WRITTEN" -eq 1 ]; then
      if [ "$REINSTALL" -eq 1 ] && [ -f "$STAGING_ROOT/rollback-skill" ]; then
        cp "$STAGING_ROOT/rollback-skill" "$CODEX_SKILL_TARGET"
      else
        rm -f "$CODEX_SKILL_TARGET"
      fi
    fi
    if [ "$RUNTIME_ROOT_CREATED" -eq 1 ]; then
      rm -f "$GATEWAY_TARGET" "$BACKEND_TARGET"
      rmdir "$(dirname "$GATEWAY_TARGET")" 2>/dev/null || true
      rmdir "$RUNTIME_TARGET_ROOT" 2>/dev/null || true
    fi
    [ "$INSTALL_ROOT_CREATED" -eq 0 ] || rm -rf "$INSTALL_ROOT"
  fi
  cleanup_staging
  exit "$status"
}
trap rollback_partial EXIT INT TERM

cp -R "${SCRIPT_DIR}/payload/marketplace/." "$STAGING_ROOT/install/marketplace/"
cp -R "${SCRIPT_DIR}/payload/clients/." "$STAGING_ROOT/install/clients/"
cp -R "${SCRIPT_DIR}/payload/codex/." "$STAGING_ROOT/install/codex/"
cp "${SCRIPT_DIR}/VERSION" "$STAGING_ROOT/install/VERSION"
cp "${SCRIPT_DIR}/bundle-manifest.json" "$STAGING_ROOT/install/bundle-manifest.json"
if [ ! -d "$INSTALL_ROOT" ]; then
  mkdir -p "$(dirname "$INSTALL_ROOT")"
  mv "$STAGING_ROOT/install" "$INSTALL_ROOT"
  INSTALL_ROOT_CREATED=1
fi
if [ -L "$CONFIG_TARGET" ] || [ ! -f "$CONFIG_TARGET" ]; then
  fail "Installed routing policy is missing or unsafe"
fi
[ "$(sha256_file "$CONFIG_TARGET")" = "$CONFIG_SHA256" ] || fail "Installed routing policy differs from this bundle"
if [ "$REINSTALL" -eq 1 ]; then
  [ "$(cat "${CURRENT_ROOT}/config_path")" = "$CONFIG_TARGET" ] || fail "Routing policy path changed since installation"
  [ "$(cat "${CURRENT_ROOT}/config_sha256")" = "$CONFIG_SHA256" ] || fail "Routing policy changed since installation"
fi

if [ "$RUNTIME_INSTALL" -eq 1 ]; then
  mkdir -p "$STAGING_ROOT/runtime/bin"
  cp "$GATEWAY_SOURCE" "$STAGING_ROOT/runtime/bin/codegraph-gateway"
  cp "$BACKEND_SOURCE" "$STAGING_ROOT/runtime/bin/codebase-memory-mcp"
  chmod 0755 "$STAGING_ROOT/runtime/bin/codegraph-gateway" "$STAGING_ROOT/runtime/bin/codebase-memory-mcp"
  if [ ! -d "$RUNTIME_TARGET_ROOT" ]; then
    mkdir -p "$(dirname "$RUNTIME_TARGET_ROOT")"
    mv "$STAGING_ROOT/runtime" "$RUNTIME_TARGET_ROOT"
    RUNTIME_ROOT_CREATED=1
  else
    [ "$(sha256_file "$GATEWAY_TARGET")" = "$GATEWAY_SHA256" ] || fail "Installed gateway differs from this bundle"
    [ "$(sha256_file "$BACKEND_TARGET")" = "$BACKEND_SHA256" ] || fail "Installed backend differs from this bundle"
  fi
fi

mkdir -p "$(dirname "$RULE_TARGET")" "$(dirname "$CODEX_SKILL_TARGET")" "$STATE_ROOT"
[ "$REINSTALL" -eq 0 ] || cp "$RULE_TARGET" "$STAGING_ROOT/rollback-rule"
[ "$REINSTALL" -eq 0 ] || cp "$CODEX_SKILL_TARGET" "$STAGING_ROOT/rollback-skill"
cp "${SCRIPT_DIR}/payload/rules/codegraph-harness.md" "$RULE_TARGET"
RULE_WRITTEN=1
cp "${SCRIPT_DIR}/payload/codex/skills/company-codegraph/SKILL.md" "$CODEX_SKILL_TARGET"
SKILL_WRITTEN=1

if [ "$SKIP_PLUGIN" -eq 0 ] && command -v claude >/dev/null 2>&1; then
  claude plugin marketplace add "${INSTALL_ROOT}/marketplace" --scope user
  MARKETPLACE_ADDED=1
  claude plugin install "$PLUGIN_ID" --scope user --yes
  PLUGIN_INSTALLED=1
fi

# Keep this canonical list in one place so Claude and Codex receive identical
# immutable gateway parameters. The administrator-selected absolute root is
# resolved before registration and the gateway rejects repositories outside it.
COMMON_GATEWAY_ARGS=(
  serve --allowed-root "$ALLOWED_ROOT"
  --data-classification public-fixture
  --state-dir "${DATA_ROOT}/graph-state"
  --cbm-binary "$BACKEND_TARGET"
  --backend-sha256 "$BACKEND_SHA256"
  --config "$CONFIG_TARGET"
  --config-sha256 "$CONFIG_SHA256"
  --git-binary "$GIT_BINARY"
  --git-sha256 "$GIT_SHA256"
)

if [ "$RUNTIME_INSTALL" -eq 1 ] && command -v claude >/dev/null 2>&1; then
  if [ "$REINSTALL" -eq 1 ] && [ "$(cat "${CURRENT_ROOT}/claude_mcp_registered")" = "1" ]; then
    CLAUDE_MCP_REGISTERED=1
    CLAUDE_MCP_SHA256="$(cat "${CURRENT_ROOT}/claude_mcp_sha256")"
  else
    claude mcp add --scope user --transport stdio "$CLAUDE_MCP_ID" -- "$GATEWAY_TARGET" "${COMMON_GATEWAY_ARGS[@]}"
    CLAUDE_MCP_REGISTERED=1
    CLAUDE_MCP_CREATED=1
    CLAUDE_MCP_SHA256="$(registration_hash claude "$CLAUDE_MCP_ID")" || fail "Could not verify Claude MCP registration"
  fi
fi

if [ "$RUNTIME_INSTALL" -eq 1 ] && command -v codex >/dev/null 2>&1; then
  if [ "$REINSTALL" -eq 1 ] && [ "$(cat "${CURRENT_ROOT}/codex_mcp_registered")" = "1" ]; then
    CODEX_MCP_REGISTERED=1
    CODEX_MCP_SHA256="$(cat "${CURRENT_ROOT}/codex_mcp_sha256")"
  else
    codex mcp add "$CODEX_MCP_ID" -- "$GATEWAY_TARGET" "${COMMON_GATEWAY_ARGS[@]}"
    CODEX_MCP_REGISTERED=1
    CODEX_MCP_CREATED=1
    CODEX_MCP_SHA256="$(registration_hash codex "$CODEX_MCP_ID")" || fail "Could not verify Codex MCP registration"
  fi
fi

NEW_RECEIPT_ROOT="${STATE_ROOT}/.current-${VERSION}-$$"
mkdir -p "$NEW_RECEIPT_ROOT"
write_receipt() { printf '%s' "$2" > "${NEW_RECEIPT_ROOT}/$1"; }
write_receipt version "$VERSION"
write_receipt install_root "$INSTALL_ROOT"
write_receipt rule_target "$RULE_TARGET"
write_receipt rule_installed_sha256 "$(sha256_file "$RULE_TARGET")"
write_receipt codex_skill_target "$CODEX_SKILL_TARGET"
write_receipt codex_skill_installed_sha256 "$(sha256_file "$CODEX_SKILL_TARGET")"
write_receipt plugin_id "$PLUGIN_ID"
write_receipt plugin_installed "$PLUGIN_INSTALLED"
write_receipt marketplace_added "$MARKETPLACE_ADDED"
write_receipt runtime_installed "$RUNTIME_INSTALL"
write_receipt runtime_platform "$PLATFORM"
write_receipt runtime_arch "$ARCH"
write_receipt runtime_root "$RUNTIME_TARGET_ROOT"
write_receipt gateway_path "$GATEWAY_TARGET"
write_receipt backend_path "$BACKEND_TARGET"
write_receipt gateway_sha256 "$GATEWAY_SHA256"
write_receipt backend_sha256 "$BACKEND_SHA256"
write_receipt claude_gateway_sha256 "$GATEWAY_SHA256"
write_receipt claude_backend_sha256 "$BACKEND_SHA256"
write_receipt codex_gateway_sha256 "$GATEWAY_SHA256"
write_receipt codex_backend_sha256 "$BACKEND_SHA256"
write_receipt config_path "$CONFIG_TARGET"
write_receipt config_sha256 "$CONFIG_SHA256"
write_receipt git_binary "$GIT_BINARY"
write_receipt git_sha256 "$GIT_SHA256"
write_receipt allowed_root "$ALLOWED_ROOT"
write_receipt claude_mcp_registered "$CLAUDE_MCP_REGISTERED"
write_receipt claude_mcp_sha256 "$CLAUDE_MCP_SHA256"
write_receipt codex_mcp_registered "$CODEX_MCP_REGISTERED"
write_receipt codex_mcp_sha256 "$CODEX_MCP_SHA256"

if [ -d "$CURRENT_ROOT" ]; then
  PREVIOUS_RECEIPT="${STATE_ROOT}/.previous-$$"
  mv "$CURRENT_ROOT" "$PREVIOUS_RECEIPT"
  mv "$NEW_RECEIPT_ROOT" "$CURRENT_ROOT"
  rm -rf "$PREVIOUS_RECEIPT"
else
  mv "$NEW_RECEIPT_ROOT" "$CURRENT_ROOT"
fi

trap rollback_partial EXIT INT TERM
printf '{"status":"success","summary":"Codegraph harness installed","next_actions":["Restart Claude Code and Codex; build indexes explicitly from approved repositories"],"artifacts":["%s"]}\n' "$CURRENT_ROOT"
