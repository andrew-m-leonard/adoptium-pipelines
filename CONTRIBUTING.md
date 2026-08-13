# Contributing to Adoptium CI Pipelines

Thank you for your interest in contributing! This document covers the basics to get you started. For deeper detail on testing, local tooling, architecture, and code style see **[docs/DEVELOPMENT_GUIDE.md](docs/DEVELOPMENT_GUIDE.md)**.

---

## Code of Conduct

This project follows the [Adoptium Code of Conduct](https://github.com/adoptium/.github/blob/main/CODE_OF_CONDUCT.md). By participating, you are expected to uphold this code.

---

## Prerequisites

- **Shell**: Bash 4.0+ (macOS users may need to upgrade via Homebrew)
- **Python**: 3.8+
- **Git**: 2.20+

---

## Getting Started

```bash
git clone https://github.com/adoptium/ci-adoptium-pipelines.git
cd ci-adoptium-pipelines

# Verify the local runner is importable
python3 ci/local/run-pipeline.py --help
```

For a full local pipeline run, see [docs/PIPELINE_RUNNER_GUIDE.md](docs/PIPELINE_RUNNER_GUIDE.md).

---

## Development Workflow

1. **Branch** — create a feature or fix branch from `main`:
   `git checkout -b feature/your-feature-name`

2. **Change** — follow the architecture and code style guidelines in [docs/DEVELOPMENT_GUIDE.md](docs/DEVELOPMENT_GUIDE.md).

3. **Test** — run linters and unit tests locally before pushing (see [docs/DEVELOPMENT_GUIDE.md](docs/DEVELOPMENT_GUIDE.md)). Linting is also enforced automatically on every PR via GitHub Actions.

4. **Commit** — use [Conventional Commits](https://www.conventionalcommits.org/) format: `<type>(<scope>): <subject>`.
   Common types: `feat`, `fix`, `docs`, `refactor`, `test`, `chore`.

5. **Push and open a PR** against `main`:
   `git push origin feature/your-feature-name`

---

## Pull Request Checklist

- [ ] Linters pass locally (black, pylint, shellcheck)
- [ ] Unit tests pass (`python3 -m unittest discover -s tests`)
- [ ] Documentation updated if behaviour changed
- [ ] Commit messages follow Conventional Commits format
- [ ] Branch is up to date with `main`

---

## Documentation

All detailed reference documentation lives in [`docs/`](docs/README.md). When making changes that affect behaviour, update the relevant doc alongside the code.

---

## Getting Help

- **Issues**: [GitHub Issues](https://github.com/adoptium/ci-adoptium-pipelines/issues)
- **Discussions**: [GitHub Discussions](https://github.com/adoptium/ci-adoptium-pipelines/discussions)
- **Slack**: [Adoptium Slack](https://adoptium.net/slack)

---

## License

By contributing, you agree that your contributions will be licensed under the Apache License 2.0.
