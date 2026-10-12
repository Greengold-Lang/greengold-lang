"""Packages: dependencies from paths, git repositories, and a registry index, pinned in `gg.lock`.

    [dependencies]
    shapes = { path = "../shapes" }                       # a directory
    json = { git = "https://example.org/json.git", tag = "v1.2.0" }   # or branch = "main", rev = "<hash>"
    http = "1.4"                                          # a version from the registry index

A git dependency is cloned once into `~/.greengold/packages` (GG_HOME overrides the location) at the
commit its tag, branch, or rev names, and that commit is written to `gg.lock`. Later builds use the
locked commit until `gg update`. A version requirement is looked up in the registry index: a directory
or git repository holding `<name>.toml` files with one `[[versions]]` entry per published version
(`version`, `git`, `rev`). "1.4" means 1.4.0 or newer below 2.0.0 (below 1.0: "0.3" means 0.3.x);
"=1.4.2" means exactly that version. The index is `[registry] index = ...` in gg.toml, else the
GG_REGISTRY environment variable. Dependencies of dependencies are resolved the same way; one name
must resolve to one source.
"""
from __future__ import annotations

import hashlib
import os
import subprocess
import tomllib
from dataclasses import dataclass
from pathlib import Path

LOCK = "gg.lock"


class PackageError(Exception):
    pass


@dataclass
class Locked:
    name: str
    source: str        # "path" | "git"
    url: str           # the path, or the git URL
    commit: str = ""   # git commit
    version: str = ""  # registry version, when it came from the registry

    def line(self) -> str:
        parts = [f'name = "{self.name}"', f'source = "{self.source}"', f'url = "{_esc(self.url)}"']
        if self.commit:
            parts.append(f'commit = "{self.commit}"')
        if self.version:
            parts.append(f'version = "{self.version}"')
        return "[[package]]\n" + "\n".join(parts) + "\n"


def _esc(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


def home() -> Path:
    return Path(os.environ.get("GG_HOME") or (Path.home() / ".greengold"))


def _git(*args: str, cwd: Path | None = None) -> str:
    res = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if res.returncode != 0:
        raise PackageError(f"git {' '.join(args[:2])} failed: {res.stderr.strip() or res.stdout.strip()}")
    return res.stdout.strip()


def _commit_of(url: str, spec: dict) -> str:
    """The commit a git dependency names: `rev` as written, else its tag or branch on the remote."""
    if "rev" in spec:
        return str(spec["rev"])
    ref = f"refs/tags/{spec['tag']}" if "tag" in spec else f"refs/heads/{spec.get('branch', 'HEAD')}"
    if "tag" not in spec and "branch" not in spec:
        ref = "HEAD"
    out = _git("ls-remote", url, ref, ref + "^{}")
    lines = [ln.split("\t") for ln in out.splitlines() if ln.strip()]
    if not lines:
        raise PackageError(f"{url}: no {ref.split('/')[-1]}")
    peeled = [h for h, r in lines if r.endswith("^{}")]  # an annotated tag points at a tag object
    return (peeled or [lines[0][0]])[0]


def _checkout(name: str, url: str, commit: str) -> Path:
    dest = home() / "packages" / f"{name}-{commit[:12]}"
    if not (dest / ".git").exists():
        dest.parent.mkdir(parents=True, exist_ok=True)
        _git("clone", "--quiet", url, str(dest))
        _git("checkout", "--quiet", commit, cwd=dest)
    return dest


def _src(root: Path) -> Path:
    return root / "src" if (root / "src").is_dir() else root


# -- registry ---------------------------------------------------------------------------------

def _index_dir(index: str) -> Path:
    """A local directory, or a git URL cloned (and refreshed) under ~/.greengold/index."""
    p = Path(index)
    if p.is_dir():
        return p
    dest = home() / "index" / hashlib.sha256(index.encode("utf-8")).hexdigest()[:16]
    if (dest / ".git").exists():
        subprocess.run(["git", "pull", "--quiet"], cwd=dest, capture_output=True)
    else:
        dest.parent.mkdir(parents=True, exist_ok=True)
        _git("clone", "--quiet", index, str(dest))
    return dest


def _version(v: str) -> tuple[int, int, int]:
    parts = (v.strip().lstrip("=").split(".") + ["0", "0", "0"])[:3]
    try:
        return int(parts[0]), int(parts[1]), int(parts[2])
    except ValueError as exc:
        raise PackageError(f"not a version: {v}") from exc


def matches(req: str, version: str) -> bool:
    """`1.4` (1.4.0 <= v < 2.0.0; below 1.0, `0.3` is 0.3.x) or `=1.4.2` (exactly)."""
    v = _version(version)
    if req.strip().startswith("="):
        return v == _version(req)
    lo = _version(req)
    hi = (lo[0] + 1, 0, 0) if lo[0] > 0 else (0, lo[1] + 1, 0)
    return lo <= v < hi


def _from_registry(name: str, req: str, index: str | None) -> tuple[str, str, str]:
    """(git url, commit, version) of the newest published version of `name` that meets `req`."""
    if not index:
        raise PackageError(f"`{name} = \"{req}\"` needs a registry: set `[registry] index` in gg.toml or GG_REGISTRY")
    entry = _index_dir(index) / f"{name}.toml"
    if not entry.is_file():
        raise PackageError(f"`{name}` is not in the registry")
    versions = tomllib.loads(entry.read_text(encoding="utf-8")).get("versions", [])
    good = [v for v in versions if matches(req, str(v.get("version", "0")))]
    if not good:
        known = ", ".join(str(v.get("version")) for v in versions) or "none"
        raise PackageError(f"no version of `{name}` meets \"{req}\" (published: {known})")
    best = max(good, key=lambda v: _version(str(v["version"])))
    return str(best["git"]), str(best["rev"]), str(best["version"])


# -- resolution -----------------------------------------------------------------------------

def read_lock(root: Path) -> dict[str, Locked]:
    path = root / LOCK
    if not path.is_file():
        return {}
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    return {p["name"]: Locked(p["name"], p["source"], p["url"], p.get("commit", ""), p.get("version", ""))
            for p in data.get("package", [])}


def write_lock(root: Path, entries: dict[str, Locked]) -> None:
    body = "# Written by gg; pins every dependency to one source. Commit it with the package.\n\n"
    body += "\n".join(entries[k].line() for k in sorted(entries))
    (root / LOCK).write_text(body, encoding="utf-8")


def resolve(root: Path, update: bool = False) -> dict[str, Path]:
    """Every dependency of the package at `root` (and theirs): name -> import root. Writes gg.lock."""
    locked = {} if update else read_lock(root)
    top = tomllib.loads((root / "gg.toml").read_text(encoding="utf-8"))
    index = (top.get("registry", {}) or {}).get("index") or os.environ.get("GG_REGISTRY")
    if index and not Path(index).is_absolute() and (root / index).is_dir():
        index = str((root / index).resolve())
    out: dict[str, Path] = {}
    found: dict[str, Locked] = {}
    todo: list[tuple[Path, str, object]] = [(root, n, s) for n, s in top.get("dependencies", {}).items()]
    while todo:
        owner, name, spec = todo.pop(0)
        if isinstance(spec, str):
            spec = {"version": spec}
        if not isinstance(spec, dict):
            raise PackageError(f"dependency `{name}`: write `{{ path = ... }}`, `{{ git = ... }}`, or a version")
        if "path" in spec:
            pkg_root = (owner / str(spec["path"])).resolve()
            if not pkg_root.is_dir():
                raise PackageError(f"dependency `{name}` not found at {pkg_root}")
            entry = Locked(name, "path", str(pkg_root))
        else:
            prev = locked.get(name)
            if "git" in spec:
                url = str(spec["git"])
                if prev is not None and prev.source == "git" and prev.url == url and not prev.version:
                    commit = prev.commit
                else:
                    commit = _commit_of(url, spec)
                entry = Locked(name, "git", url, commit)
            elif "version" in spec:
                req = str(spec["version"])
                if prev is not None and prev.version and matches(req, prev.version):
                    entry = prev
                else:
                    url, commit, version = _from_registry(name, req, index)
                    entry = Locked(name, "git", url, commit, version)
            else:
                raise PackageError(f"dependency `{name}`: write `{{ path = ... }}`, `{{ git = ... }}`, or a version")
            pkg_root = _checkout(name, entry.url, entry.commit)
        same = found.get(name)
        if same is not None:
            if (same.source, same.url, same.commit) != (entry.source, entry.url, entry.commit):
                raise PackageError(f"`{name}` is required from two sources: {same.url}@{same.commit[:12] or '-'} "
                                   f"and {entry.url}@{entry.commit[:12] or '-'}")
            continue
        found[name] = entry
        out[name] = _src(pkg_root)
        manifest = pkg_root / "gg.toml"
        if manifest.is_file():
            deps = tomllib.loads(manifest.read_text(encoding="utf-8")).get("dependencies", {})
            todo.extend((pkg_root, n, s) for n, s in deps.items())
    write_lock(root, found)
    return out


# -- publishing -----------------------------------------------------------------------------

def publish(root: Path, index: str) -> str:
    """Adds this package's version at its current commit to a registry index directory."""
    data = tomllib.loads((root / "gg.toml").read_text(encoding="utf-8"))
    pkg = data.get("package", {})
    name, version = pkg.get("name"), str(pkg.get("version", ""))
    repo = pkg.get("repository")
    if not name or not version:
        raise PackageError("gg.toml needs [package] name and version")
    if not repo:
        raise PackageError("gg.toml needs [package] repository = \"<git url others can clone>\"")
    if _git("status", "--porcelain", cwd=root):
        raise PackageError("commit your changes first: the registry records a commit")
    commit = _git("rev-parse", "HEAD", cwd=root)
    idx = Path(index)
    if not idx.is_dir():
        raise PackageError(f"the registry index must be a local directory (a checkout of the index): {index}")
    entry = idx / f"{name}.toml"
    old = tomllib.loads(entry.read_text(encoding="utf-8")).get("versions", []) if entry.is_file() else []
    if any(str(v.get("version")) == version for v in old):
        raise PackageError(f"{name} {version} is already published; raise the version in gg.toml")
    with entry.open("a", encoding="utf-8") as f:
        f.write(f'[[versions]]\nversion = "{version}"\ngit = "{_esc(str(repo))}"\nrev = "{commit}"\n\n')
    if (idx / ".git").exists():
        _git("add", entry.name, cwd=idx)
        _git("commit", "--quiet", "-m", f"{name} {version}", cwd=idx)
    return f"{name} {version} at {commit[:12]}"
