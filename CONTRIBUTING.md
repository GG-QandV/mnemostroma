# Contributing to Mnemostroma

Thank you for your interest in contributing to Mnemostroma! Mnemostroma is a local-first, lightweight, offline-first memory layer for AI agents. By contributing, you help make agentic workflows more continuous, private, and powerful.

Please read the following guidelines to ensure a smooth contribution process.

---

## 1. Core Architectural Principles

Before writing any code, please keep our core architectural constraints in mind:
* **Silent Writing**: Memory is written silently by observers. AI agents must only read from memory and act upon it.
* **Offline-First & Lightweight**: The database uses SQLite (WAL mode). Embedding models and NER engines run locally via **ONNX Runtime** (CPU thread pool).
* **Minimal Stack**: Do not introduce heavy dependencies. Core tools allowed: `onnxruntime`, `tokenizers`, `numpy`, `lz4`, `aiosqlite`.
* **Async by Default**: All main runtime I/O paths must use `async/await`. CPU-heavy work (e.g. ONNX inference) must run in executors to avoid blocking the event loop.

---

## 2. Git Workflow

We follow a structured Git flow to keep our repository clean and history linear:

### Branches
* `main` — Contains stable, released code. Direct commits are restricted to emergency hotfixes.
* `feat/<name>` — For new features.
* `fix/<name>` — For bug fixes.
* `refactor/<name>` — For refactoring.

### Commit Format
We enforce **Conventional Commits**. Please format your commit messages as:
```text
<type>(<scope>): <short description>
```
* **Types**: `feat`, `fix`, `refactor`, `test`, `docs`, `chore`.
* **Scopes**: `core`, `storage`, `observer`, `integration`, `tools`, `extension`.
* **Example**: `feat(observer): add active variable classification heuristics`

---

## 3. Coding Standards

### Python (Core & Daemon)
* **Strict Typing**: All public functions and methods must have complete type hints. Avoid `Any` unless strictly necessary.
* **Logging**: Use structured logger imports. Never use `print()` in production code. Redact and never log sensitive customer payloads or credentials.
* **Memory Safety**: When initializing ONNX Runtime inference sessions, always disable default internal allocators to prevent RSS memory leaks:
  ```python
  opts.enable_cpu_mem_arena = False
  opts.enable_mem_pattern = False
  ```

### Browser Extension (TypeScript / JavaScript)
* **Types**: Use TypeScript correctly without resorting to `as any` or `@ts-ignore` suppressions.
* **Dependencies**: Never commit the `node_modules/` folder or temporary build assets (`.vite`, `.vitest`, build caches).

---

## 4. Submitting Pull Requests

1. **Write Tests**: Every new feature or bug fix must be accompanied by relevant unit or integration tests under the `tests/` directory.
2. **Verify Tests Pass**: Make sure all tests run successfully:
   ```bash
   pytest tests/
   ```
3. **Lint & Format**: Run linting checks before committing:
   * For Python: Ensure code adheres to PEP 8 standards.
   * For the browser extension: Run `eslint . --fix` and `npx tsc --noEmit`.
4. **No TODOs in PRs**: Do not leave orphan `TODO`, `FIXME`, or `HACK` markers. If a task is not finished, resolve it or log it into the project task tracker.

---

## 5. Security & Privacy

* **Secrets Safety**: Never commit `.env` files, API keys, credentials, or development tokens.
* **Private Data**: Never include production database dumps (`.db` files) or instrumentation logs in your commits.

By contributing to this repository, you agree that your contributions will be licensed under the project's [LICENSE](LICENSE) terms.
