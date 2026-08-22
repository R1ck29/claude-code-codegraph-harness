"""Build deterministic, reviewable Claude Code harness distribution bundles.

The public bundle is assembled only from repository-owned text/configuration
assets.  An internal profile may add pre-staged vendor files, but every such
file must be named explicitly and match its declared SHA-256 digest.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import sys
import tempfile
from typing import Any, Iterable, Mapping, NoReturn
import unicodedata
import zipfile

SCHEMA_VERSION = "1.0"
_ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)
_DIRECTORY_MAPPINGS = (
    (".claude-plugin", "payload/marketplace/.claude-plugin"),
    ("plugins", "payload/marketplace/plugins"),
    ("rules", "payload/rules"),
)
_FILE_MAPPINGS = (
    ("installers/macos/install.sh", "install.sh"),
    ("installers/macos/uninstall.sh", "uninstall.sh"),
    ("installers/windows/install.ps1", "install.ps1"),
    ("installers/windows/uninstall.ps1", "uninstall.ps1"),
    ("LICENSE", "LICENSE"),
    ("THIRD_PARTY_NOTICES.md", "THIRD_PARTY_NOTICES.md"),
    ("README-INSTALL.txt", "README-INSTALL.txt"),
    ("docs/how-it-works-ja.md", "HOW-IT-WORKS-JA.md"),
)
_EXCLUDED_DIRECTORY_NAMES = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        ".cache",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        "__pycache__",
        "cache",
        "caches",
        "result",
        "results",
    }
)
_SECRET_SUFFIXES = frozenset({".key", ".pem", ".p12", ".pfx", ".jks", ".keystore"})
_VENDOR_BINARY_SUFFIXES = frozenset(
    {
        ".7z",
        ".a",
        ".bin",
        ".class",
        ".dll",
        ".dmg",
        ".dylib",
        ".exe",
        ".gz",
        ".jar",
        ".lib",
        ".msi",
        ".o",
        ".obj",
        ".pkg",
        ".pyc",
        ".rar",
        ".so",
        ".tar",
        ".wasm",
        ".zip",
    }
)
_GENERATED_PATHS = frozenset(
    {"VERSION", "profile.json", "bundle-manifest.json", "SHA256SUMS"}
)
_VERSION_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_PROFILE_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_WINDOWS_RESERVED_NAMES = frozenset(
    {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *(f"COM{number}" for number in range(1, 10)),
        *(f"LPT{number}" for number in range(1, 10)),
    }
)


class BundleError(ValueError):
    """Raised when a bundle cannot be built safely."""


def _json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _collision_key(path: str) -> str:
    """Use the strictest common key for Windows/macOS extraction."""
    return unicodedata.normalize("NFC", path).casefold()


def _validated_relative_path(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise BundleError(f"{field} must be a non-empty relative path")
    if "\x00" in value or "\\" in value or value.startswith("/"):
        raise BundleError(f"{field} must be a portable relative path: {value!r}")
    if re.match(r"^[A-Za-z]:", value):
        raise BundleError(f"{field} must be a portable relative path: {value!r}")
    raw_parts = value.split("/")
    if any(part in {"", ".", ".."} for part in raw_parts):
        raise BundleError(f"{field} must be a normalized relative path: {value!r}")
    for part in raw_parts:
        if any(character in part for character in '<>:"|?*'):
            raise BundleError(f"{field} is not portable to Windows: {value!r}")
        if part.endswith((" ", ".")):
            raise BundleError(f"{field} is not portable to Windows: {value!r}")
        stem = part.split(".", 1)[0].upper()
        if stem in _WINDOWS_RESERVED_NAMES:
            raise BundleError(f"{field} is not portable to Windows: {value!r}")
    normalized = PurePosixPath(*raw_parts).as_posix()
    if normalized != value:
        raise BundleError(f"{field} must be a normalized relative path: {value!r}")
    return normalized


def _is_excluded(relative_path: PurePosixPath) -> bool:
    if any(
        part.casefold() in _EXCLUDED_DIRECTORY_NAMES for part in relative_path.parts
    ):
        return True
    name = relative_path.name.casefold()
    if name == ".env" or name.startswith(".env."):
        return True
    if name in {"credentials.json", "secrets.json", "id_rsa", "id_ed25519"}:
        return True
    suffix = relative_path.suffix.casefold()
    return suffix in _SECRET_SUFFIXES or suffix in _VENDOR_BINARY_SUFFIXES


def _has_binary_magic(data: bytes) -> bool:
    prefixes = (
        b"MZ",  # Portable Executable
        b"\x7fELF",
        b"\xfe\xed\xfa\xce",
        b"\xce\xfa\xed\xfe",
        b"\xfe\xed\xfa\xcf",
        b"\xcf\xfa\xed\xfe",
        b"\xca\xfe\xba\xbe",
        b"\x00asm",
    )
    return data.startswith(prefixes)


def _ensure_no_symlink(path: Path, *, boundary: Path, label: str) -> None:
    boundary_absolute = boundary.absolute()
    path_absolute = path.absolute()
    try:
        relative = path_absolute.relative_to(boundary_absolute)
    except ValueError as error:
        raise BundleError(f"{label} resolves out-of-root: {path}") from error
    current = boundary_absolute
    if current.is_symlink():
        raise BundleError(f"{label} must not use a symlink: {current}")
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise BundleError(f"{label} must not use a symlink: {current}")


def _read_regular_file(path: Path, *, boundary: Path, label: str) -> bytes:
    _ensure_no_symlink(path, boundary=boundary, label=label)
    try:
        resolved_boundary = boundary.resolve(strict=True)
        resolved_path = path.resolve(strict=True)
    except (FileNotFoundError, OSError) as error:
        raise BundleError(f"{label} does not exist: {path}") from error
    try:
        resolved_path.relative_to(resolved_boundary)
    except ValueError as error:
        raise BundleError(f"{label} resolves out-of-root: {path}") from error
    if not resolved_path.is_file():
        raise BundleError(f"{label} must be a regular file: {path}")
    try:
        return resolved_path.read_bytes()
    except OSError as error:
        raise BundleError(f"could not read {label}: {path}: {error}") from error


def _load_profile(profile_path: Path) -> dict[str, Any]:
    if profile_path.is_symlink():
        raise BundleError(f"profile must not be a symlink: {profile_path}")
    try:
        raw = json.loads(profile_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise BundleError(f"invalid profile JSON: {profile_path}: {error}") from error
    if not isinstance(raw, dict):
        raise BundleError("profile must be a JSON object")
    allowed_keys = {
        "schema_version",
        "profile_id",
        "kind",
        "description",
        "vendor_files",
    }
    unknown = sorted(set(raw) - allowed_keys)
    if unknown:
        raise BundleError(f"profile contains unknown fields: {', '.join(unknown)}")
    if raw.get("schema_version") != SCHEMA_VERSION:
        raise BundleError(f"profile schema_version must be {SCHEMA_VERSION!r}")
    profile_id = raw.get("profile_id")
    if not isinstance(profile_id, str) or not _PROFILE_ID_PATTERN.fullmatch(profile_id):
        raise BundleError("profile_id must match ^[a-z0-9][a-z0-9._-]*$")
    kind = raw.get("kind")
    if kind not in {"public", "internal"}:
        raise BundleError("profile kind must be 'public' or 'internal'")
    description = raw.get("description")
    if not isinstance(description, str):
        raise BundleError("profile description must be a string")
    vendor_files = raw.get("vendor_files")
    if not isinstance(vendor_files, list):
        raise BundleError("profile vendor_files must be an array")
    if kind == "public" and vendor_files:
        raise BundleError("public profile must not enumerate vendor files")

    normalized_vendor_files: list[dict[str, str]] = []
    for index, entry in enumerate(vendor_files):
        if not isinstance(entry, dict) or set(entry) != {"source", "target", "sha256"}:
            raise BundleError(
                f"vendor_files[{index}] must contain only source, target, and sha256"
            )
        source = _validated_relative_path(
            entry["source"], field=f"vendor_files[{index}].source"
        )
        target = _validated_relative_path(
            entry["target"], field=f"vendor_files[{index}].target"
        )
        sha256 = entry["sha256"]
        if not isinstance(sha256, str) or not _SHA256_PATTERN.fullmatch(sha256):
            raise BundleError(
                f"vendor_files[{index}].sha256 must be 64 lowercase hexadecimal characters"
            )
        normalized_vendor_files.append(
            {"source": source, "target": target, "sha256": sha256}
        )

    normalized_vendor_files.sort(key=lambda item: (item["target"], item["source"]))
    return {
        "schema_version": SCHEMA_VERSION,
        "profile_id": profile_id,
        "kind": kind,
        "description": description,
        "vendor_files": normalized_vendor_files,
    }


def _iter_repository_files(repo_root: Path) -> Iterable[tuple[str, bytes]]:
    for source_root, target_root in _DIRECTORY_MAPPINGS:
        candidate = repo_root / source_root
        if candidate.is_symlink():
            raise BundleError(f"repository input must not use a symlink: {candidate}")
        if not candidate.is_dir():
            raise BundleError(
                f"required repository directory is missing: {source_root}"
            )

        included_count = 0
        root_path = candidate
        for current_string, directory_names, file_names in os.walk(
            root_path, topdown=True, followlinks=False
        ):
            current = Path(current_string)
            kept_directories: list[str] = []
            for directory_name in sorted(directory_names):
                directory = current / directory_name
                relative = PurePosixPath(directory.relative_to(repo_root).as_posix())
                if _is_excluded(relative):
                    continue
                if directory.is_symlink():
                    raise BundleError(
                        f"repository input must not use a symlink: {directory}"
                    )
                kept_directories.append(directory_name)
            directory_names[:] = kept_directories

            for file_name in sorted(file_names):
                path = current / file_name
                relative_string = path.relative_to(repo_root).as_posix()
                relative = PurePosixPath(relative_string)
                if _is_excluded(relative):
                    continue
                data = _read_regular_file(
                    path, boundary=repo_root, label="repository input"
                )
                if _has_binary_magic(data[:8]):
                    continue
                included_count += 1
                suffix = path.relative_to(root_path).as_posix()
                yield f"{target_root}/{suffix}", data
        if included_count == 0:
            raise BundleError(
                f"repository has no distributable files under {source_root}"
            )

    required_marketplace = repo_root / ".claude-plugin" / "marketplace.json"
    if not required_marketplace.is_file():
        raise BundleError(
            "required repository file is missing: .claude-plugin/marketplace.json"
        )
    required_rule = repo_root / "rules" / "codegraph-harness.md"
    if not required_rule.is_file():
        raise BundleError(
            "required repository file is missing: rules/codegraph-harness.md"
        )

    for source, target in _FILE_MAPPINGS:
        path = repo_root.joinpath(*PurePosixPath(source).parts)
        if not path.exists():
            raise BundleError(f"required repository file is missing: {source}")
        data = _read_regular_file(path, boundary=repo_root, label="repository input")
        if _is_excluded(PurePosixPath(source)) or _has_binary_magic(data[:8]):
            raise BundleError(f"required repository file is excluded: {source}")
        yield target, data


def _add_entry(
    entries: dict[str, tuple[bytes, str]],
    collision_keys: dict[str, str],
    *,
    target: str,
    data: bytes,
    source: str,
) -> None:
    target = _validated_relative_path(target, field="bundle target")
    key = _collision_key(target)
    if key in collision_keys:
        raise BundleError(
            f"duplicate target {target!r}; already provided by {collision_keys[key]!r}"
        )
    collision_keys[key] = target
    entries[target] = (data, source)


def _vendor_entries(
    profile: Mapping[str, Any], vendor_dir: Path | None
) -> Iterable[tuple[str, bytes]]:
    vendor_files = profile["vendor_files"]
    if not vendor_files:
        return
    if vendor_dir is None:
        raise BundleError("vendor_dir is required when an internal profile lists files")
    if vendor_dir.is_symlink():
        raise BundleError(f"vendor_dir must not be a symlink: {vendor_dir}")
    try:
        vendor_root = vendor_dir.resolve(strict=True)
    except (FileNotFoundError, OSError) as error:
        raise BundleError(f"vendor_dir does not exist: {vendor_dir}") from error
    if not vendor_root.is_dir():
        raise BundleError(f"vendor_dir must be a directory: {vendor_dir}")

    for entry in vendor_files:
        source_path = vendor_root.joinpath(*PurePosixPath(entry["source"]).parts)
        data = _read_regular_file(
            source_path, boundary=vendor_root, label="vendor source"
        )
        actual_digest = _digest(data)
        if actual_digest != entry["sha256"]:
            raise BundleError(
                "vendor hash mismatch for "
                f"{entry['source']!r}: expected {entry['sha256']}, got {actual_digest}"
            )
        yield entry["target"], data


def _manifest(
    entries: Mapping[str, tuple[bytes, str]],
    *,
    version: str,
    profile: Mapping[str, Any],
) -> dict[str, Any]:
    artifacts = [
        {
            "path": path,
            "sha256": _digest(data),
            "size": len(data),
            "source": source,
        }
        for path, (data, source) in sorted(entries.items())
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "success",
        "summary": "Deterministic Claude Code harness bundle assembled and verified.",
        "next_actions": [
            "Verify every entry against SHA256SUMS after transfer.",
            "Follow README-INSTALL.txt for the target operating system.",
        ],
        "artifacts": artifacts,
        "version": version,
        "profile": {
            "profile_id": profile["profile_id"],
            "kind": profile["kind"],
        },
    }


def _zip_info(path: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(path, date_time=_ZIP_TIMESTAMP)
    info.create_system = 3
    info.compress_type = zipfile.ZIP_DEFLATED
    info.flag_bits = 0x800
    mode = 0o755 if path.endswith((".sh", ".command")) else 0o644
    info.external_attr = (stat.S_IFREG | mode) << 16
    return info


def _write_zip(output_path: Path, entries: Mapping[str, bytes]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix=f".{output_path.name}.",
            suffix=".tmp",
            dir=output_path.parent,
            delete=False,
        ) as temporary:
            temporary_name = temporary.name
        with zipfile.ZipFile(
            temporary_name,
            mode="w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=9,
            strict_timestamps=True,
        ) as archive:
            for path in sorted(entries):
                archive.writestr(
                    _zip_info(path),
                    entries[path],
                    compress_type=zipfile.ZIP_DEFLATED,
                    compresslevel=9,
                )
        os.replace(temporary_name, output_path)
        temporary_name = None
    except OSError as error:
        raise BundleError(f"could not write bundle {output_path}: {error}") from error
    finally:
        if temporary_name is not None:
            try:
                Path(temporary_name).unlink()
            except FileNotFoundError:
                pass


def build_bundle(
    repo_root: str | os.PathLike[str],
    output_path: str | os.PathLike[str],
    *,
    version: str,
    profile_path: str | os.PathLike[str],
    vendor_dir: str | os.PathLike[str] | None = None,
) -> dict[str, Any]:
    """Build a deterministic bundle and return a machine-readable response.

    ``vendor_dir`` is never scanned.  Only files enumerated by an ``internal``
    profile, and verified against that profile's SHA-256 values, are included.
    """
    if not isinstance(version, str) or not _VERSION_PATTERN.fullmatch(version):
        raise BundleError(
            "version must contain only letters, numbers, dot, underscore, or hyphen"
        )

    root = Path(repo_root).resolve()
    if not root.is_dir():
        raise BundleError(f"repo_root must be a directory: {repo_root}")
    profile = _load_profile(Path(profile_path))
    vendor_path = Path(vendor_dir) if vendor_dir is not None else None

    entries: dict[str, tuple[bytes, str]] = {}
    collision_keys: dict[str, str] = {}
    for generated_path in _GENERATED_PATHS:
        collision_keys[_collision_key(generated_path)] = generated_path

    for target, data in _iter_repository_files(root):
        _add_entry(
            entries,
            collision_keys,
            target=target,
            data=data,
            source="repository",
        )
    for target, data in _vendor_entries(profile, vendor_path):
        _add_entry(
            entries,
            collision_keys,
            target=target,
            data=data,
            source="vendor",
        )

    version_data = f"{version}\n".encode("utf-8")
    profile_data = _json_bytes(profile)
    entries["VERSION"] = (version_data, "generated")
    entries["profile.json"] = (profile_data, "generated")
    manifest_data = _json_bytes(_manifest(entries, version=version, profile=profile))

    zip_entries = {path: data for path, (data, _) in entries.items()}
    zip_entries["bundle-manifest.json"] = manifest_data
    sums = "".join(
        f"{_digest(zip_entries[path])}  {path}\n" for path in sorted(zip_entries)
    ).encode("utf-8")
    zip_entries["SHA256SUMS"] = sums

    output = Path(output_path).resolve()
    _write_zip(output, zip_entries)
    bundle_data = output.read_bytes()
    return {
        "status": "success",
        "summary": (f"Created deterministic {profile['kind']} bundle {output.name}."),
        "next_actions": [
            "Publish the ZIP and its SHA-256 through the approved release channel.",
            "Test installation on clean Windows and macOS hosts.",
        ],
        "artifacts": [
            {
                "path": str(output),
                "sha256": _digest(bundle_data),
                "size": len(bundle_data),
            }
        ],
    }


class _ArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        raise BundleError(message)


def run_bundle_cli(args: list[str]) -> int:
    """Run the bundle subcommand with arguments supplied by the root CLI."""
    arguments = list(args)
    if arguments and arguments[0] == "build":
        arguments.pop(0)
    parser = _ArgumentParser(prog="codegraph-harness bundle")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--output")
    parser.add_argument("--version", required=True)
    parser.add_argument("--profile", default="packaging/profiles/public.json")
    parser.add_argument("--vendor-dir")
    try:
        namespace = parser.parse_args(arguments)
        output = namespace.output or str(
            Path(namespace.repo_root)
            / "dist"
            / f"codegraph-harness-{namespace.version}.zip"
        )
        response = build_bundle(
            namespace.repo_root,
            output,
            version=namespace.version,
            profile_path=namespace.profile,
            vendor_dir=namespace.vendor_dir,
        )
    except BundleError as error:
        response = {
            "status": "error",
            "summary": str(error),
            "next_actions": ["Correct the reported input and run bundle again."],
            "artifacts": [],
        }
        print(json.dumps(response, ensure_ascii=False, sort_keys=True), file=sys.stderr)
        return 2
    except SystemExit as exit_signal:
        return exit_signal.code if isinstance(exit_signal.code, int) else 1
    print(json.dumps(response, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover - root CLI normally calls the function.
    raise SystemExit(run_bundle_cli(sys.argv[1:]))
