# Freshness requirements

A graph result is usable only when its metadata can be matched to the current workspace.

Record and compare:

- repository identity;
- commit SHA;
- dirty state or an explicit statement that dirty files are unsupported;
- worktree identity;
- backend and backend version;
- graph schema version;
- include/exclude configuration hash;
- build time and build result.

If these values do not match, mark the result stale and fall back to source exploration. Never present stale structural output as current repository state.
