import pytest

from hazzel import config


@pytest.fixture
def nudge_file(tmp_path, monkeypatch):
    path = tmp_path / ".star_nudged"
    monkeypatch.setattr(config, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(config, "STAR_NUDGE_FILE", path)
    monkeypatch.delenv("HAZZEL_NO_NAG", raising=False)
    return path


def test_fresh_install_never_nudges(nudge_file):
    assert not nudge_file.exists()
    assert config.should_show_star_nudge() is False


def test_nudge_fires_after_threshold_turns(nudge_file):
    nudge_file.write_text("4", encoding="utf-8")
    assert config.should_show_star_nudge() is False
    nudge_file.write_text(str(config.STAR_NUDGE_THRESHOLD), encoding="utf-8")
    assert config.should_show_star_nudge() is True


def test_bump_counts_up_and_nudge_shows_once(nudge_file):
    for _ in range(config.STAR_NUDGE_THRESHOLD):
        config.bump_star_nudge_count()
    assert config.should_show_star_nudge() is True
    config.mark_star_nudged()
    assert config.should_show_star_nudge() is False
    # already-asked users stay quiet even as they keep working
    config.bump_star_nudge_count()
    assert config.should_show_star_nudge() is False


def test_hazzel_no_nag_opt_out(nudge_file, monkeypatch):
    nudge_file.write_text("99", encoding="utf-8")
    monkeypatch.setenv("HAZZEL_NO_NAG", "1")
    assert config.should_show_star_nudge() is False
    monkeypatch.setenv("HAZZEL_NO_NAG", "false")
    assert config.should_show_star_nudge() is False
    monkeypatch.setenv("HAZZEL_NO_NAG", "")
    assert config.should_show_star_nudge() is True
    monkeypatch.setenv("HAZZEL_NO_NAG", "0")
    assert config.should_show_star_nudge() is True


def test_legacy_touched_file_counts_as_zero(nudge_file):
    # pre-1.5.3 created an empty marker at first launch. Count it as zero so
    # existing users get one *earned* ask (after 5 turns) instead of the old
    # unearned launch-time one — but still only ever once.
    nudge_file.touch()
    assert config.should_show_star_nudge() is False


def test_corrupt_file_counts_as_zero(nudge_file):
    nudge_file.write_text("not-a-number", encoding="utf-8")
    assert config.should_show_star_nudge() is False
