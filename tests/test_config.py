import pytest

from lkml_ground_truth.config import load_config


def _write_config(tmp_path, repo_section=""):
    content = f"""
{repo_section}
[paths]
repo_path = "resources/linux/repo"
dataset_root = "{str(tmp_path)}"
list_name = "netdev"
output_path = "output/matches_{{list}}.csv"
commit_index_cache = "commit_index_cache.pickle"

[performance]
num_workers = 2
rebuild_index = false
chunksize = 50
progress_every = 500

[matching]
days_before = 3
days_after = 365
autoaccept = 0.8
interactive = 0.5
diff_lines_ratio = 0.4
heading = 0.7
filename = 0.7
message_diff_weight = 0.5
"""

    config_path = tmp_path / "config.toml"
    config_path.write_text(content)
    return config_path


def test_load_config_reads_sections(tmp_path):
    config_path = _write_config(tmp_path)

    config = load_config(config_path)

    assert config.paths.list_name == "netdev"
    assert config.performance.num_workers == 2
    assert config.matching.autoaccept == pytest.approx(0.8)


def test_resolved_num_workers_uses_configured_value(tmp_path):
    config = load_config(_write_config(tmp_path))
    assert config.performance.resolved_num_workers() == 2


def test_resolved_output_path_substitutes_list_name(tmp_path):
    config = load_config(_write_config(tmp_path))
    assert config.paths.resolved_output_path("bpf") == "output/matches_bpf.csv"


def test_available_lists_reads_list_subdirectories(tmp_path):
    (tmp_path / "list=netdev").mkdir()
    (tmp_path / "list=bpf").mkdir()
    (tmp_path / "not-a-list").mkdir()

    config = load_config(_write_config(tmp_path))

    assert config.paths.available_lists() == ["bpf", "netdev"]


def test_load_config_missing_file_raises_actionable_error(tmp_path):
    with pytest.raises(FileNotFoundError, match="example_config.toml"):
        load_config(tmp_path / "does-not-exist.toml")


def test_repo_config_defaults_to_manual_clone_when_section_absent(tmp_path):
    """Configs antigas, sem [repo], continuam funcionando (auto_clone off)."""
    config = load_config(_write_config(tmp_path))

    assert config.repo.auto_clone is False
    assert config.repo.since == ""
    assert config.repo.is_shallow() is False


def test_repo_config_reads_explicit_values(tmp_path):
    repo_section = """
[repo]
auto_clone = true
clone_url = "https://example.invalid/linux.git"
since = "2020-01-01"
"""
    config = load_config(_write_config(tmp_path, repo_section=repo_section))

    assert config.repo.auto_clone is True
    assert config.repo.clone_url == "https://example.invalid/linux.git"
    assert config.repo.since == "2020-01-01"
    assert config.repo.is_shallow() is True
