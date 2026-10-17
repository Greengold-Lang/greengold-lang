"""`gg update`: replaces the installed standalone `gg` with the newest GitHub release.

Release assets are one archive per platform (`gg-windows-x64.zip`, `gg-linux-x64.tar.gz`, `gg-linux-arm64.tar.gz`,
`gg-macos-arm64.tar.gz`, `gg-macos-x64.tar.gz`) and `SHA256SUMS.txt`; `.github/workflows/release.yml` publishes
them. An archive holds the program next to its `_internal` folder, with no wrapping folder.
Only a standalone build (the installers, `tools/build_standalone.py`) can replace itself; a `pip` or source
install is told how to update with its own tool.
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

REPO = os.environ.get("GG_REPO", "Greengold-Lang/greengold-lang")
API = f"https://api.github.com/repos/{REPO}/releases"
SUMS = "SHA256SUMS.txt"
TIMEOUT = 30
ASIDE = ".gg-old"   # where the replaced files wait; Windows cannot delete a running program
STAGED = ".gg-staged"   # the new folder waiting for this gg to exit (Windows keeps some files open while it runs)


class UpdateError(Exception):
    pass


def platform_asset() -> str:
    """The release asset name for this machine."""
    system = {"win32": "windows", "linux": "linux", "darwin": "macos"}.get(sys.platform)
    machine = platform.machine().lower()
    arch = {"x86_64": "x64", "amd64": "x64", "arm64": "arm64", "aarch64": "arm64"}.get(machine)
    if system is None or arch is None:
        raise UpdateError(f"no prebuilt gg for {sys.platform}/{machine}; build it from source")
    return f"gg-{system}-{arch}" + (".zip" if system == "windows" else ".tar.gz")


def parse_version(text: str) -> tuple[tuple[int, ...], int]:
    """`v0.3.4` -> ((0, 3, 4), 1); a pre-release (`0.4.0-rc1`) sorts before its release."""
    m = re.match(r"v?(\d+(?:\.\d+)*)(?:[-+.]?(\w.*))?$", text.strip())
    if not m:
        raise UpdateError(f"cannot read the version `{text}`")
    return tuple(int(p) for p in m.group(1).split(".")), (0 if m.group(2) else 1)


def is_newer(candidate: str, current: str) -> bool:
    return parse_version(candidate) > parse_version(current)


def _request(url: str, accept: str | None = None) -> urllib.request.Request:
    headers = {"User-Agent": "greengold-gg-update"}
    if accept:
        headers["Accept"] = accept
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token and url.startswith("https://api.github.com/"):
        headers["Authorization"] = f"Bearer {token}"
    return urllib.request.Request(url, headers=headers)


def fetch_release(tag: str | None) -> dict:
    url = f"{API}/tags/{tag if tag.startswith('v') else 'v' + tag}" if tag else f"{API}/latest"
    try:
        with urllib.request.urlopen(_request(url, "application/vnd.github+json"), timeout=TIMEOUT) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as err:
        if err.code == 404:
            raise UpdateError(f"no release {tag or '(latest)'} found in {REPO}") from None
        if err.code in (403, 429):
            raise UpdateError("GitHub refused the request (rate limit?); try again later "
                              "or set GITHUB_TOKEN") from None
        raise UpdateError(f"GitHub answered HTTP {err.code}") from None
    except (urllib.error.URLError, TimeoutError, OSError) as err:
        raise UpdateError(f"cannot reach GitHub: {getattr(err, 'reason', err)}") from None


def _download(url: str, dest: Path, label: str) -> None:
    try:
        with urllib.request.urlopen(_request(url, "application/octet-stream"), timeout=TIMEOUT) as resp, \
                open(dest, "wb") as out:
            total = int(resp.headers.get("Content-Length") or 0)
            done = 0
            while chunk := resp.read(1 << 20):
                out.write(chunk)
                done += len(chunk)
                if total and sys.stderr.isatty():
                    print(f"\r{label}: {done / 1e6:.0f} / {total / 1e6:.0f} MB", end="", file=sys.stderr)
            if total and sys.stderr.isatty():
                print(file=sys.stderr)
    except (urllib.error.URLError, TimeoutError, OSError) as err:
        raise UpdateError(f"download of {label} failed: {getattr(err, 'reason', err)}") from None


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


def parse_sums(text: str) -> dict[str, str]:
    """`sha256sum` output: `<hex>  <name>` per line."""
    sums = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) == 2:
            sums[parts[1].lstrip("*")] = parts[0].lower()
    return sums


def installed_binary() -> Path | None:
    """The file to replace, or None when gg runs from pip or a source checkout."""
    return Path(sys.executable).resolve() if getattr(sys, "frozen", False) else None


def _files(root: Path) -> list[Path]:
    """Every non-directory under `root` (a symlink counts as a file), relative to it."""
    found = []
    for base, dirs, names in os.walk(root):
        for name in list(dirs):
            if (Path(base) / name).is_symlink():
                dirs.remove(name)
                names.append(name)
        found += [(Path(base) / name).relative_to(root) for name in names]
    return found


def extract(archive: Path, dest: Path) -> None:
    dest.mkdir()
    if archive.name.endswith(".zip"):
        with zipfile.ZipFile(archive) as z:
            z.extractall(dest)
    else:
        with tarfile.open(archive) as t:
            if hasattr(tarfile, "data_filter"):
                t.extractall(dest, filter="data")
            else:
                t.extractall(dest)


def replace_running(new: Path, target: Path) -> None:
    """Swap the program folder `new` in for the one holding `target`, which may be running. Windows cannot
    overwrite or delete a loaded .exe or .dll but can rename it, so each old file moves aside one by one into
    `.gg-old` (deleted by the next update). Only names the new folder has are touched, because the install
    folder may be shared (`/usr/local/bin`). A failure puts everything back."""
    home = target.parent
    aside = home / ASIDE
    shutil.rmtree(aside, ignore_errors=True)
    ours = {p.parts[0] for p in _files(new)}
    old = [rel for name in ours if (home / name).exists() for rel in
           ([Path(name)] if not (home / name).is_dir() or (home / name).is_symlink()
            else [Path(name) / r for r in _files(home / name)])]
    moved: list[Path] = []
    placed: list[Path] = []
    try:
        for rel in old:
            (aside / rel).parent.mkdir(parents=True, exist_ok=True)
            os.replace(home / rel, aside / rel)
            moved.append(rel)
        for rel in _files(new):
            (home / rel).parent.mkdir(parents=True, exist_ok=True)
            os.replace(new / rel, home / rel)
            placed.append(rel)
    except OSError:
        # Undo as much as possible; one stuck file must not stop the rest from being restored.
        for rel in placed:
            try:
                (home / rel).unlink()
            except OSError:
                pass
        for rel in moved:
            try:
                (home / rel).parent.mkdir(parents=True, exist_ok=True)
                os.replace(aside / rel, home / rel)
            except OSError:
                pass
        raise
    if sys.platform != "win32":
        os.chmod(target, 0o755)


def finish_after_exit(new: Path, target: Path) -> None:
    """Windows only. A running gg keeps files like `_internal\\base_library.zip` open, so they cannot even be renamed.
    Park the new folder in `.gg-staged` and start a hidden PowerShell that waits for this process to exit, then
    moves the folder over the install (robocopy retries files an antivirus scan still holds)."""
    home = target.parent
    staged = home / STAGED
    shutil.rmtree(staged, ignore_errors=True)
    os.replace(new, staged)
    backup = home / ASIDE
    # Keep the old install until the copy has succeeded: a failed robocopy (exit code >= 8) restores it, so `gg`
    # is never left without its `_internal` folder.
    script = (f'$p = {os.getpid()}; while (Get-Process -Id $p -ErrorAction SilentlyContinue) {{ Start-Sleep -Milliseconds 200 }}; '
              f'Remove-Item -LiteralPath "{backup}" -Recurse -Force -ErrorAction SilentlyContinue; '
              f'New-Item -ItemType Directory -Force -Path "{backup}" | Out-Null; '
              f'Move-Item -LiteralPath "{home}\\_internal" -Destination "{backup}\\_internal" -Force -ErrorAction SilentlyContinue; '
              f'robocopy "{staged}" "{home}" /E /MOVE /IS /IT /R:30 /W:1 /NFL /NDL /NJH /NJS /NP | Out-Null; '
              f'if ($LASTEXITCODE -ge 8) {{ '
              # Mirror, never Move-Item: if the half-copied `_internal` could not be fully removed, Move-Item would
              # nest the old one inside it (`_internal\\_internal`) and gg would no longer find python312.dll.
              f'robocopy "{backup}\\_internal" "{home}\\_internal" /MIR /IS /IT /R:30 /W:1 /NFL /NDL /NJH /NJS /NP | Out-Null }}; '
              f'Remove-Item -LiteralPath "{staged}" -Recurse -Force -ErrorAction SilentlyContinue')
    flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW   # DETACHED_PROCESS + CREATE_NO_WINDOW fails
    subprocess.Popen(["powershell", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden", "-Command", script],
                     creationflags=flags, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def cleanup_old() -> None:
    exe = installed_binary()
    if exe is not None:
        shutil.rmtree(exe.parent / ASIDE, ignore_errors=True)
        try:
            exe.with_name(exe.name + ".old").unlink()   # left by the single-file builds
        except OSError:
            pass


def _not_standalone_hint() -> str:
    if (Path(__file__).resolve().parent.parent / ".git").exists():
        return "this is a source checkout: run `git pull` in it"
    return ("this gg was installed with pip: run `pip install -U "
            f"git+https://github.com/{REPO}.git`, or install the standalone build "
            f"(https://github.com/{REPO}#install) to make `gg update` work")


def run(check_only: bool = False, force: bool = False, tag: str | None = None) -> int:
    from . import __version__
    cleanup_old()
    try:
        release = fetch_release(tag)
        latest = release["tag_name"]
        newer = is_newer(latest, __version__)
        if check_only or (not newer and not force and not tag):
            if newer:
                print(f"gg {latest} is available (this is {__version__}). Run `gg update`.")
            else:
                print(f"gg {__version__} is up to date.")
            return 0
        if not force and not newer:
            print(f"gg {__version__} is already newer than or equal to {latest}; use --force to install it anyway.")
            return 0
        target = installed_binary()
        if target is None:
            raise UpdateError(_not_standalone_hint())
        wanted = platform_asset()
        assets = {a["name"]: a["browser_download_url"] for a in release.get("assets", [])}
        if wanted not in assets:
            raise UpdateError(f"release {latest} has no `{wanted}` file")
        if not os.access(target.parent, os.W_OK):
            raise UpdateError(f"no permission to write {target.parent}; run `gg update` as the user who installed gg "
                              "(or with sudo)")
        print(f"Updating gg {__version__} -> {latest} ({wanted})")
        with tempfile.TemporaryDirectory(dir=target.parent, prefix=".gg-update-") as tmp:
            archive = Path(tmp) / wanted
            _download(assets[wanted], archive, wanted)
            if SUMS in assets:
                print("Verifying...", flush=True)
                sums_file = Path(tmp) / SUMS
                _download(assets[SUMS], sums_file, SUMS)
                expect = parse_sums(sums_file.read_text(encoding="utf-8")).get(wanted)
                if expect is None or expect != _sha256(archive):
                    raise UpdateError("the downloaded file does not match its SHA-256 in SHA256SUMS.txt; "
                                      "nothing was changed")
            else:
                print("warning: this release has no SHA256SUMS.txt; the download was not verified", file=sys.stderr)
            new = Path(tmp) / "new"
            print("Unpacking...", flush=True)
            try:
                extract(archive, new)
            except (zipfile.BadZipFile, tarfile.TarError) as err:
                raise UpdateError(f"cannot unpack {wanted}: {err}") from None
            fresh = new / target.name
            if not fresh.is_file():
                raise UpdateError(f"{wanted} has no `{target.name}`; nothing was changed")
            os.chmod(fresh, 0o755)
            print("Checking that the new gg starts (the first start can take a while)...", flush=True)
            probe = subprocess.run([str(fresh), "--version"], capture_output=True, text=True, timeout=120)
            if probe.returncode != 0:
                raise UpdateError("the downloaded gg does not start on this machine; nothing was changed\n"
                                  + probe.stderr.strip())
            print("Installing...", flush=True)
            try:
                replace_running(new, target)
            except PermissionError as err:
                if sys.platform != "win32" or getattr(err, "winerror", None) not in (5, 32):
                    raise
                finish_after_exit(new, target)
                print(f"gg {latest} will be in place a few seconds after this command exits ({target}).")
                return 0
        print(f"gg {latest} is installed at {target}")
        return 0
    except UpdateError as err:
        print(f"Error: {err}", file=sys.stderr)
        return 1
    except (subprocess.SubprocessError, OSError) as err:
        print(f"Error: update failed: {err}", file=sys.stderr)
        if getattr(err, "winerror", None) in (5, 32):   # access denied / sharing violation: a file is in use
            print("Another program is using gg's files. Close VS Code (the Greengold extension runs gg), other "
                  "terminals and editors that run gg, then run `gg update` again. Nothing was changed.", file=sys.stderr)
        return 1
