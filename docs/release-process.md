# Release process

## Public release

1. Confirm `candidates/registry.json` still describes the intended evaluation inputs.
2. Run the full test, plugin validation, archive, and public-sanitization checks.
3. Review all changes and confirm no internal data or vendor artifact is present.
4. Tag the reviewed commit with `v<version>`.
5. Build the public profile bundle from that tag.
6. Publish the ZIP and its SHA-256 as release assets.

The release workflow accepts only a `v*` tag and derives the bundle version from it. GitHub's generated source archives are not endpoint installers.

## Internal release

An internal release is a separate artifact assembled from an immutable public tag plus approved private inputs. Record:

- public commit and tag;
- private profile hash;
- every injected artifact hash and provenance record;
- test matrix and results;
- signing identity;
- software-portal artifact hash;
- the separate channel or signing policy used to authenticate that hash;
- rollback owner and retention period.

Never rebuild an already published internal version with different bytes. Increment the internal version instead.

The internal runtime release must use the four-platform profile, but its public
source release remains adapter-only. Record each gateway/backend executable hash,
the compile-time fixture allowlist and matching runtime-profile value, selected
endpoint pair, allowed root, managed Git identity, index manifest, and
install→index→query→uninstall result. Do not publish a company-source runtime
until the signed enterprise gate in `docs/internal-integration.md` passes.

The endpoint must verify the complete ZIP against that separately stored hash or signature before extraction. `SHA256SUMS` is inside the ZIP and therefore cannot authenticate a fully replaced archive by itself.
