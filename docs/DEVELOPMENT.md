# Development guide

Lumina is a personal Linux-focused application. The main package and CLI retain the historical `local_coder` name.

## Prerequisites

- Python 3.11 or later, a virtual environment, and the dependencies declared in `pyproject.toml`
- An independently configured local Ollama inference service and suitable installed models for AI-assisted features
- Linux services and sandbox tools for full coding-agent functionality; a Python installation alone does not provide the full runtime

Hardware, model availability, and service configuration vary. Do **not** assume the repository's original host paths, GPU layout, or LAN settings apply to another machine.

## Install for development

```bash
git clone https://github.com/Alden-Gerald/Lumina.git
cd Lumina
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
local-coder --help
```

For a local dashboard after required services are configured:

```bash
local-coder serve
```

The dashboard is designed to use loopback networking. Do not publish the development HTTP server directly on an untrusted network.

## Run checks

```bash
python -m unittest discover -s tests -v
python -m compileall -q local_coder
```

These checks should be run on the developer's machine. Some tests require Linux-specific tools or installed dependencies. See [verification](verification.md) for historical results; those are not results for your present checkout.

## Code layout

- `local_coder/`: runtime logic, HTTP server, task controller, file tools and browser UI
- `integrations/`: optional third-party / desktop integrations
- `config/` and `services/`: service-oriented host configuration
- `scripts/`: setup and maintenance utilities
- `tests/`: tests and behavioral regressions
- `docs/`: architecture decisions, experiments and plans

## Safe change workflow

1. Create a branch and define a small expected behavior.
2. Read nearby code and tests before editing; preserve the existing names and interfaces unless changing them intentionally.
3. Make small changes with focused tests. Never weaken a failing test just to obtain a passing result.
4. Review patches for credentials, local paths, internal IP addresses, personal information, and accidental generated files.
5. Run relevant checks before requesting review. Prefer a pull request over direct changes to `main`.

## Security and reporting

The coding agent operates on disposable snapshots and validates changes before applying them. This mitigates certain accidental edits; it does not make generated code inherently safe. Review code before running it.

Keep passwords, private keys, tokens, local model files, user attachments and logs out of commits. Do not copy the author’s local LAN gateway configuration without redesigning it for your environment. See [SECURITY.md](../SECURITY.md).
