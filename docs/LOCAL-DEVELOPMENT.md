# Local development bootstrap

The project uses `pyproject.toml` as the authoritative dependency declaration. The `requirements*.txt` files are compatibility entry points for developers and automation that expect `pip install -r ...`.

## Clean environment

```text
python -m venv .venv
```

Activate the virtual environment using the normal command for your shell, then upgrade packaging tools:

```text
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
python -m pytest
```

For PostgreSQL adapter work:

```text
python -m pip install -r requirements-postgres.txt
```

Or install both extras directly from the authoritative package metadata:

```text
python -m pip install -e ".[dev,postgres]"
```

## Important

Do not install PaddlePaddle, PyTorch/Qwen, Docling, and Surya into this core development environment merely to run the core tests. Model-provider runtimes use isolated deployment profiles under `deploy/runtime-profiles/`.

The supported Python baseline is declared in `pyproject.toml`. If installation fails, verify the active interpreter before changing package constraints:

```text
python --version
python -m pip --version
```
