"""Dependencies from git and a registry index, pinned in gg.lock (`gg fetch`, `gg update`, `gg publish`)."""
import os
import subprocess
from pathlib import Path

import pytest

from greengold import packages
from greengold.cli import main

pytestmark = pytest.mark.skipif(subprocess.run(["git", "--version"], capture_output=True).returncode != 0,
                                reason="git is not installed")


def git(cwd: Path, *args: str) -> str:
    res = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True)
    return res.stdout.strip()


def make_repo(path: Path, name: str, version: str, body: str, deps: str = "") -> None:
    (path / "src").mkdir(parents=True)
    (path / "gg.toml").write_text(f'[package]\nname = "{name}"\nversion = "{version}"\n'
                                  f'repository = "{path.as_uri()}"\n\n[dependencies]\n{deps}', encoding="utf-8")
    (path / "src" / f"{name}.gg").write_text(body, encoding="utf-8")
    git(path, "init", "-q")
    git(path, "-c", "user.email=t@t", "-c", "user.name=t", "add", "-A")
    git(path, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "v" + version)
    git(path, "tag", "v" + version)


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("GG_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("GG_REGISTRY", raising=False)
    old = os.getcwd()
    yield tmp_path
    os.chdir(old)


def test_git_and_registry_dependencies(env, capsys):
    make_repo(env / "shapes", "shapes", "1.0.0", "fn area(w: i32, h: i32) -> i32:\n    return w * h\n")
    make_repo(env / "geom", "geom", "1.1.0",
              "import shapes.shapes\n\nfn square(n: i32) -> i32:\n    return shapes.area(n, n)\n",
              deps=f'shapes = {{ git = "{(env / "shapes").as_uri()}", tag = "v1.0.0" }}\n')
    index = env / "index"
    index.mkdir()
    os.chdir(env / "geom")
    assert main(["publish", "--index", str(index)]) == 0
    assert "geom 1.1.0" in capsys.readouterr().out
    assert main(["publish", "--index", str(index)]) == 1  # the same version twice

    app = env / "app"
    (app / "src").mkdir(parents=True)
    (app / "gg.toml").write_text('[package]\nname = "app"\nversion = "0.1.0"\n\n[registry]\nindex = "../index"\n\n'
                                 '[dependencies]\ngeom = "1.0"\n', encoding="utf-8")
    (app / "src" / "main.gg").write_text("import geom.geom\n\nfn main():\n    print(geom.square(7))\n",
                                          encoding="utf-8")
    os.chdir(app)
    assert main(["fetch"]) == 0
    lock = packages.read_lock(app)
    assert set(lock) == {"geom", "shapes"} and lock["geom"].version == "1.1.0"
    assert len(lock["shapes"].commit) == 40
    exe = app / ("app.exe" if os.name == "nt" else "app")
    assert main(["build", "-o", str(exe)]) == 0
    assert subprocess.run([str(exe)], capture_output=True, text=True).stdout.strip() == "49"


def test_version_requirements():
    assert packages.matches("1.4", "1.9.2") and not packages.matches("1.4", "2.0.0")
    assert not packages.matches("1.4", "1.3.9")
    assert packages.matches("0.3", "0.3.7") and not packages.matches("0.3", "0.4.0")
    assert packages.matches("=1.2.3", "1.2.3") and not packages.matches("=1.2.3", "1.2.4")


def test_lock_keeps_the_commit_until_update(env):
    make_repo(env / "lib", "lib", "1.0.0", "fn one() -> i32:\n    return 1\n")
    app = env / "app"
    (app / "src").mkdir(parents=True)
    (app / "gg.toml").write_text('[package]\nname = "app"\nversion = "0.1.0"\n\n[dependencies]\n'
                                 f'lib = {{ git = "{(env / "lib").as_uri()}", branch = "master" }}\n', encoding="utf-8")
    try:
        git(env / "lib", "branch", "-M", "master")
    except subprocess.CalledProcessError:
        pass
    packages.resolve(app)
    first = packages.read_lock(app)["lib"].commit
    (env / "lib" / "src" / "lib.gg").write_text("fn one() -> i32:\n    return 2\n", encoding="utf-8")
    git(env / "lib", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qam", "two")
    packages.resolve(app)
    assert packages.read_lock(app)["lib"].commit == first
    packages.resolve(app, update=True)
    assert packages.read_lock(app)["lib"].commit != first


def test_two_sources_for_one_name_is_an_error(env):
    make_repo(env / "a", "a", "1.0.0", "fn f() -> i32:\n    return 1\n")
    make_repo(env / "b", "b", "1.0.0", "fn g() -> i32:\n    return 1\n",
              deps=f'a = {{ path = "{(env / "a").as_posix()}" }}\n')
    app = env / "app"
    app.mkdir()
    other = env / "a2"
    make_repo(other, "a", "1.0.0", "fn f() -> i32:\n    return 2\n")
    (app / "gg.toml").write_text('[package]\nname = "app"\nversion = "0.1.0"\n\n[dependencies]\n'
                                 f'a = {{ path = "{other.as_posix()}" }}\nb = {{ path = "{(env / "b").as_posix()}" }}\n',
                                 encoding="utf-8")
    with pytest.raises(packages.PackageError, match="two sources"):
        packages.resolve(app)
