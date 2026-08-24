"""Sessões de lint e teste, executadas localmente ou via CI (make test / CI)."""

import nox

nox.options.reuse_existing_virtualenvs = True


@nox.session
def lint(session: nox.Session) -> None:
    session.install("ruff≃0.8.04")
    session.run("ruff", "check", ".")


@nox.session
def tests(session: nox.Session) -> None:
    session.install("-e", ".")
    session.install("pytest", "pytest-cov")
    session.run(
        "pytest",
        "--cov=lkml_ground_truth",
        "--cov-report=term-missing",
        "--cov-report=html",
        *session.posargs,
    )
