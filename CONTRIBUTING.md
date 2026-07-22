# Contributing to Scribe Dictation

## Pre-commit hooks

This repo uses the [`pre-commit`](https://pre-commit.com/) framework
(`.pre-commit-config.yaml`) to enforce, on every commit:

- **Format check** — `ruff` (lint, `--fix`) and `ruff-format`.
- **Secret scan** — `gitleaks`, plus `detect-private-key` from
  `pre-commit-hooks`, block commits that contain credentials or private keys.
- **Brand / program-affiliation lint** — `scripts/brand_lint.py` blocks
  README/CONTRIBUTING/CHANGELOG/docs changes that introduce a sibling
  product's brand name or 12-step-program-affiliation language onto this
  repo's public surface. Wordlist: `.githooks/brand-wordlist.txt`. This is
  the same convention used in sibling repos in this owner's ecosystem
  (see `.githooks/` in e.g. Cairn), adapted here to plug into the
  `pre-commit` framework instead of a bash `.githooks/` dispatcher, since
  this repo already standardized on `pre-commit` + `ruff`/`gitleaks` (see
  `.pre-commit-config.yaml` history) rather than the raw-bash git-guards kit.
- Misc hygiene — trailing whitespace, end-of-file, YAML/TOML validity.

### Enable it

This repo's `core.hooksPath` is already set to `.githooks` (a checked-in,
per-clone-auto-enabled hooks dir — the same convention used across this
owner's other repos, e.g. Cairn). `.githooks/pre-commit` bridges that to the
`pre-commit` framework config above, so all you need is the `pre-commit`
tool itself:

```bash
pip install pre-commit   # or: uv tool install pre-commit
```

That's it — no `pre-commit install` needed (and it will refuse to run,
since `core.hooksPath` is already pointed at `.githooks`). If `pre-commit`
isn't installed, the hook prints a warning and lets the commit through
rather than blocking contributors who haven't set it up yet.

Hooks now run automatically on `git commit`. To run them against the whole
tree once (e.g. after enabling for the first time):

```bash
pre-commit run --all-files
```

### Bypassing (rare, and only when you mean it)

```bash
git commit --no-verify
```

For the brand-lint hook specifically, a scoped override is also available:

```bash
ALLOW_BRAND_STRINGS=1 git commit -m "..."
```

### Format check locally without committing

```bash
uv run ruff check .
uv run ruff format --check .
```
