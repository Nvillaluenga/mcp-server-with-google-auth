# How to contribute

## Prerequisites

Refer to the `Prerequisites` section in `README.md` for instructions on setting up
your local environment for this project.

## Install pre-commit

Set up `pre-commit` on your local development environment to lint and autoformat the
code. This makes the code review process easier.

The `pre-commit` dependency should have already been installed when you did your
[Prerequisites](#prerequisites).

To install the `pre-commit` configuration defined in `pre-commit-config.yaml`, run:
```
pre-commit install --hook-type pre-commit --hook-type pre-push
```

## Making code changes

Follow the [GitHub flow](https://docs.github.com/en/get-started/using-github/github-flow)
style by creating Git branches for code changes and creating a pull request (PR),
which should be reviewed and approved before merging to the `main` branch.


## Adding dependencies

Use `uv` to add new package dependencies rather than `pip`.

```bash
uv add PACKAGE_NAME
```

This will add a dependency in the `dependencies` field in the `pyproject.toml` file.

Add the `--dev` flag for development-only packages.

For example:
```bash
uv add --dev ruff
```

This will add the package, `ruff`, in a separate table in the `pyproject.toml` file,

e.g.
```

[tool.uv]
dev-dependencies = [
    "ruff>=0.6.8",
]
```