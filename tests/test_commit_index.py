from lkml_ground_truth.commit_index import _parse_git_log_dump, find_candidates

GIT_LOG_DUMP = (
    "\x01aaaa111 1000\n"
    "net/core/dev.c\n"
    "drivers/net/foo.c\n"
    "\n"
    "\x01bbbb222 2000\n"
    "net/core/dev.c\n"
)


def test_parse_git_log_dump_groups_by_file_sorted_by_time():
    index = _parse_git_log_dump(GIT_LOG_DUMP)

    assert index["net/core/dev.c"] == [(1000, "aaaa111"), (2000, "bbbb222")]
    assert index["drivers/net/foo.c"] == [(1000, "aaaa111")]


def test_find_candidates_filters_by_time_window():
    index = _parse_git_log_dump(GIT_LOG_DUMP)

    candidates = find_candidates(index, ["net/core/dev.c"], since_ts=0, until_ts=1500)

    assert candidates == {"aaaa111"}


def test_find_candidates_ignores_unknown_files():
    index = _parse_git_log_dump(GIT_LOG_DUMP)

    candidates = find_candidates(index, ["does/not/exist.c"], since_ts=0, until_ts=9999)

    assert candidates == set()


def test_find_candidates_unions_multiple_files():
    index = _parse_git_log_dump(GIT_LOG_DUMP)

    candidates = find_candidates(
        index, ["net/core/dev.c", "drivers/net/foo.c"], since_ts=0, until_ts=9999
    )

    assert candidates == {"aaaa111", "bbbb222"}
