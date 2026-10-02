# Contributing

1. Install into a local venv: `python -m pip install -e ".[dev]"`.
2. Run `python -m pytest` before opening a change.
3. Run `ruff check .` and `mypy atlas`.
4. Scope every read/write to the project directory.
5. Never commit secrets, `.env`, databases, or generated artifacts (see
   `.gitignore`).
6. No fabricated results: benchmarks must be reproducible from the repository;
   claims about performance must come from measured runs recorded under
   `reports/` or `experiments/output/`.