# Contributing

Contributions are welcome for vendor-neutral evaluation, safer offline packaging, documentation, and reproducible tests.

## Development

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e .
python -m unittest discover -s tests -v
claude plugin validate --strict ./plugins/codegraph-evaluator
claude plugin validate --strict .
```

Keep runtime code on the Python standard library unless an ADR justifies a dependency. Use `apply_patch`-sized focused changes and include tests.

## Public-data boundary

Use synthetic fixtures or clearly redistributable public fixtures. Never attach internal code, prompts, results, paths, configuration, screenshots, or logs to an issue or pull request.

## Commit messages

Use conventional commits such as `feat:`, `fix:`, `docs:`, `test:`, and `chore:`.
