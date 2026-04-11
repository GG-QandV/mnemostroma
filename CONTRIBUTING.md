# Contributing to Mnemostroma

Thank you for your interest in contributing. This document covers how to report bugs, suggest features, and submit code.

---

## Reporting Bugs

Open an issue at [github.com/GG-QandV/mnemostroma/issues](https://github.com/GG-QandV/mnemostroma/issues/new/choose).

Please include:

- OS and Python version
- `mnemostroma status` output
- Steps to reproduce
- What you expected vs what happened
- Relevant snippet from `~/.mnemostroma/daemon.log` (if applicable)

---

## Suggesting Features

Open an issue with the **enhancement** label. Describe:

- What problem it solves
- How you'd expect it to work
- Whether it affects the Observer, MCP tools, storage, or proxy

---

## Submitting Code

1. Fork the repository
2. Create a branch: `git checkout -b fix/my-fix` or `feat/my-feature`
3. Make your changes
4. Run tests: `pytest tests/` (requires `pip install -e ".[dev]"`)
5. Open a pull request against `main`

### What makes a good PR

- Focused — one fix or feature per PR
- Tests included for any new behaviour
- No changes to `pyproject.toml` version field (maintainer handles releases)
- Commit messages follow conventional format: `fix:`, `feat:`, `docs:`, `refactor:`

### What we won't merge

- Changes to the Observer write path that allow agents to write memory directly
- New MCP tools that duplicate existing retrieval tools
- Dependencies outside the declared core (`onnxruntime, tokenizers, numpy, lz4, aiosqlite`)
- Anything that requires a running cloud service or GPU

---

## Development Setup

```bash
git clone https://github.com/GG-QandV/mnemostroma.git
cd mnemostroma
pip install -e ".[dev]"
pytest tests/
```

Fast test run (skips slow contract tests, ~14s):
```bash
pytest tests/ --ignore=tests/test_memory_layers.py \
              --ignore=tests/test_data_contracts.py
```

---

## Maintenance Cadence

This is a solo-developer project. Issues and PRs are reviewed in weekly batches (usually weekends). Expect a response within 7 days.

---

## License

By submitting a pull request, you agree that your contribution will be licensed under the same [FSL-1.1-MIT](LICENSE) terms as the rest of the project.
