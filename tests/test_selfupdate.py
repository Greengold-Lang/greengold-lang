"""`gg update`: version comparison, asset names, checksum check, and replacing the installed file."""
import hashlib
import sys

import pytest

from greengold import selfupdate


def test_versions_compare_numerically():
    assert selfupdate.is_newer("v0.3.10", "0.3.9")
    assert selfupdate.is_newer("0.4.0", "0.3.99")
    assert not selfupdate.is_newer("0.3.3", "0.3.3")
    assert not selfupdate.is_newer("v0.3.2", "0.3.3")
    assert not selfupdate.is_newer("0.4.0-rc1", "0.4.0")


def test_bad_version_is_an_error():
    with pytest.raises(selfupdate.UpdateError):
        selfupdate.parse_version("latest")


@pytest.mark.parametrize("plat,machine,name", [
    ("win32", "AMD64", "gg-windows-x64.exe"),
    ("linux", "x86_64", "gg-linux-x64"),
    ("linux", "aarch64", "gg-linux-arm64"),
    ("darwin", "arm64", "gg-macos-arm64"),
    ("darwin", "x86_64", "gg-macos-x64"),
])
def test_asset_names(monkeypatch, plat, machine, name):
    monkeypatch.setattr(sys, "platform", plat)
    monkeypatch.setattr(selfupdate.platform, "machine", lambda: machine)
    assert selfupdate.platform_asset() == name


def test_unknown_machine(monkeypatch):
    monkeypatch.setattr(selfupdate.platform, "machine", lambda: "riscv64")
    with pytest.raises(selfupdate.UpdateError):
        selfupdate.platform_asset()


def test_parse_sums():
    text = "AB12  gg-linux-x64\ncd34 *gg-windows-x64.exe\n\n"
    assert selfupdate.parse_sums(text) == {"gg-linux-x64": "ab12", "gg-windows-x64.exe": "cd34"}


def test_replace_running_swaps_the_file(tmp_path):
    target = tmp_path / "gg"
    target.write_bytes(b"old")
    new = tmp_path / "new"
    new.write_bytes(b"new")
    selfupdate.replace_running(new, target)
    assert target.read_bytes() == b"new"
    assert not new.exists()
    if sys.platform == "win32":
        assert (tmp_path / "gg.old").read_bytes() == b"old"
        selfupdate.replace_running(_file(tmp_path / "newer", b"newer"), target)  # an old .old is replaced
        assert target.read_bytes() == b"newer"


def _file(path, data):
    path.write_bytes(data)
    return path


def test_not_standalone_is_told_how_to_update(monkeypatch, capsys):
    monkeypatch.setattr(selfupdate, "fetch_release", lambda tag: {"tag_name": "v99.0.0", "assets": []})
    monkeypatch.setattr(selfupdate, "installed_binary", lambda: None)
    assert selfupdate.run() == 1
    assert "Error:" in capsys.readouterr().err


def test_up_to_date(monkeypatch, capsys):
    from greengold import __version__
    monkeypatch.setattr(selfupdate, "fetch_release", lambda tag: {"tag_name": "v" + __version__, "assets": []})
    assert selfupdate.run() == 0
    assert "up to date" in capsys.readouterr().out


def test_check_only_does_not_install(monkeypatch, capsys):
    monkeypatch.setattr(selfupdate, "fetch_release", lambda tag: {"tag_name": "v99.0.0", "assets": []})
    assert selfupdate.run(check_only=True) == 0
    assert "v99.0.0 is available" in capsys.readouterr().out


def test_checksum_mismatch_changes_nothing(monkeypatch, tmp_path, capsys):
    exe = tmp_path / "gg"
    exe.write_bytes(b"old")
    wanted = selfupdate.platform_asset()
    release = {"tag_name": "v99.0.0", "assets": [
        {"name": wanted, "browser_download_url": "x://bin"},
        {"name": selfupdate.SUMS, "browser_download_url": "x://sums"}]}

    def fake_download(url, dest, label):
        dest.write_bytes(b"payload" if url == "x://bin" else f"{'0' * 64}  {wanted}\n".encode())

    monkeypatch.setattr(selfupdate, "fetch_release", lambda tag: release)
    monkeypatch.setattr(selfupdate, "_download", fake_download)
    monkeypatch.setattr(selfupdate, "installed_binary", lambda: exe)
    assert selfupdate.run() == 1
    assert "SHA-256" in capsys.readouterr().err
    assert exe.read_bytes() == b"old"
    assert hashlib.sha256(b"payload").hexdigest() != "0" * 64
