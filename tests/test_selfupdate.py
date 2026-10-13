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
    ("win32", "AMD64", "gg-windows-x64.zip"),
    ("linux", "x86_64", "gg-linux-x64.tar.gz"),
    ("linux", "aarch64", "gg-linux-arm64.tar.gz"),
    ("darwin", "arm64", "gg-macos-arm64.tar.gz"),
    ("darwin", "x86_64", "gg-macos-x64.tar.gz"),
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


def _tree(root, files):
    for rel, data in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_bytes(data)


def test_replace_running_swaps_the_folder(tmp_path):
    home = tmp_path / "home"
    new = tmp_path / "new"
    _tree(home, {"gg": b"old", "_internal/a.dll": b"a1", "_internal/gone.dll": b"x", "other-tool": b"keep"})
    _tree(new, {"gg": b"new", "_internal/a.dll": b"a2", "_internal/sub/b.dll": b"b2"})
    selfupdate.replace_running(new, home / "gg")
    assert (home / "gg").read_bytes() == b"new"
    assert (home / "_internal/a.dll").read_bytes() == b"a2"
    assert (home / "_internal/sub/b.dll").read_bytes() == b"b2"
    assert not (home / "_internal/gone.dll").exists()
    assert (home / "other-tool").read_bytes() == b"keep"
    assert (home / selfupdate.ASIDE / "gg").read_bytes() == b"old"
    _tree(tmp_path / "newer", {"gg": b"newer"})
    selfupdate.replace_running(tmp_path / "newer", home / "gg")   # an earlier .gg-old is cleared
    assert (home / "gg").read_bytes() == b"newer"


def test_replace_running_puts_everything_back_on_failure(tmp_path, monkeypatch):
    home = tmp_path / "home"
    new = tmp_path / "new"
    _tree(home, {"gg": b"old", "_internal/a.dll": b"a1"})
    _tree(new, {"gg": b"new", "_internal/a.dll": b"a2"})
    real = selfupdate.os.replace
    calls = []

    def flaky(src, dst):
        calls.append(src)
        if str(src).startswith(str(new)) and len(calls) > 3:
            raise OSError("locked")
        real(src, dst)

    monkeypatch.setattr(selfupdate.os, "replace", flaky)
    with pytest.raises(OSError):
        selfupdate.replace_running(new, home / "gg")
    monkeypatch.undo()
    assert (home / "gg").read_bytes() == b"old"
    assert (home / "_internal/a.dll").read_bytes() == b"a1"


@pytest.mark.parametrize("name", ["x.zip", "x.tar.gz"])
def test_extract_reads_both_archive_kinds(tmp_path, name):
    src = tmp_path / "src"
    _tree(src, {"gg": b"g", "_internal/a": b"a"})
    import shutil
    archive = tmp_path / name
    if name.endswith(".zip"):
        shutil.make_archive(str(tmp_path / "x"), "zip", src)
    else:
        shutil.make_archive(str(tmp_path / "x"), "gztar", src)
    out = tmp_path / "out"
    selfupdate.extract(archive, out)
    assert (out / "gg").read_bytes() == b"g" and (out / "_internal/a").read_bytes() == b"a"


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
