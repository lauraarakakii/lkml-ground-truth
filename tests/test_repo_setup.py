import subprocess

import pytest

from lkml_ground_truth.config import RepoConfig
from lkml_ground_truth.repo_setup import ensure_repo


def _init_real_git_repo(path):
    path.mkdir(parents=True)
    subprocess.run(["git", "init", "--quiet", str(path)], check=True)


def test_ensure_repo_skips_clone_when_repo_already_exists(tmp_path, monkeypatch):
    repo_path = tmp_path / "linux"
    _init_real_git_repo(repo_path)

    def _fail_if_called(*args, **kwargs):
        raise AssertionError("git clone should not have been called")

    monkeypatch.setattr(subprocess, "run", _fail_if_called)

    # Does not raise and does not attempt cloning.
    ensure_repo(RepoConfig(auto_clone=True), str(repo_path))


def test_ensure_repo_raises_actionable_error_when_auto_clone_disabled(tmp_path):
    repo_path = tmp_path / "does-not-exist"

    with pytest.raises(FileNotFoundError, match="auto_clone"):
        ensure_repo(RepoConfig(auto_clone=False), str(repo_path))


def test_ensure_repo_raises_when_path_exists_but_is_not_a_git_repo(tmp_path):
    repo_path = tmp_path / "not-a-repo"
    repo_path.mkdir()
    (repo_path / "some_file.txt").write_text("oops")

    with pytest.raises(FileNotFoundError, match="does not look like a valid Git clone"):
        ensure_repo(RepoConfig(auto_clone=True), str(repo_path))


def test_ensure_repo_clones_with_shallow_since_when_configured(tmp_path, monkeypatch):
    repo_path = tmp_path / "linux"
    captured_cmd = {}

    def _fake_run(cmd, **kwargs):
        captured_cmd["cmd"] = cmd
        repo_path.mkdir(parents=True)
        (repo_path / ".git").mkdir()
        return subprocess.CompletedProcess(cmd, returncode=0)

    monkeypatch.setattr(subprocess, "run", _fake_run)

    ensure_repo(
        RepoConfig(
            auto_clone=True,
            clone_url="https://example.invalid/linux.git",
            since="2020-01-01",
        ),
        str(repo_path),
    )

    assert "--shallow-since=2020-01-01" in captured_cmd["cmd"]
    assert "https://example.invalid/linux.git" in captured_cmd["cmd"]


def test_ensure_repo_clones_full_history_when_since_not_set(tmp_path, monkeypatch):
    repo_path = tmp_path / "linux"
    captured_cmd = {}

    def _fake_run(cmd, **kwargs):
        captured_cmd["cmd"] = cmd
        repo_path.mkdir(parents=True)
        (repo_path / ".git").mkdir()
        return subprocess.CompletedProcess(cmd, returncode=0)

    monkeypatch.setattr(subprocess, "run", _fake_run)

    ensure_repo(RepoConfig(auto_clone=True), str(repo_path))

    assert not any(arg.startswith("--shallow-since=") for arg in captured_cmd["cmd"])


def test_ensure_repo_raises_runtime_error_when_clone_fails(tmp_path, monkeypatch):
    repo_path = tmp_path / "linux"

    def _fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, returncode=128)

    monkeypatch.setattr(subprocess, "run", _fake_run)

    with pytest.raises(RuntimeError, match="git clone"):
        ensure_repo(RepoConfig(auto_clone=True), str(repo_path))
