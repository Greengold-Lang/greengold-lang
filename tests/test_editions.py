"""Editions in gg.toml, and the version flag."""
import pytest

from greengold import editions, tools


def manifest(tmp_path, extra=""):
    path = tmp_path / "gg.toml"
    path.write_text(f'[package]\nname = "p"\nversion = "0.1.0"\n{extra}', encoding="utf-8")
    return path


def test_edition_defaults_to_latest(tmp_path):
    assert tools.load_manifest(manifest(tmp_path)).edition == editions.LATEST


def test_unknown_edition_is_an_error(tmp_path):
    with pytest.raises(ValueError, match='unknown edition "2019"'):
        tools.load_manifest(manifest(tmp_path, 'edition = "2019"\n'))


def test_gg_new_writes_the_edition(tmp_path):
    assert tools.cmd_new("demo", str(tmp_path / "demo")) == 0
    text = (tmp_path / "demo" / "gg.toml").read_text(encoding="utf-8")
    assert f'edition = "{editions.LATEST}"' in text


def test_version_flag(capsys):
    from greengold.cli import main
    with pytest.raises(SystemExit):
        main(["--version"])
    assert "language editions: 2026" in capsys.readouterr().out
