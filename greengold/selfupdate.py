"""`gg update`: replaces the installed single-file `gg` with the newest GitHub release.

Release assets are one file per platform (`gg-windows-x64.exe`, `gg-linux-x64`, `gg-linux-arm64`,
`gg-macos-arm64`, `gg-macos-x64`) and `SHA256SUMS.txt`; `.github/workflows/release.yml` publishes them.
Only a standalone build (the installers, `tools/build_standalone.py`) can replace itself; a `pip` or source
install is told how to update with its own tool.
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

REPO = os.environ.get("GG_REPO", "Greengold-Lang/greengold-lang")
API = f"https://api.github.com/repos/{REPO}/releases"
SUMS = "SHA256SUMS.txt"
TIMEOUT = 30


class UpdateError(Exception):
    pass


def platform_asset() -> str:
    """The release asset name for this machine."""
    system = {"win32": "windows", "linux": "linux", "darwin": "macos"}.get(sys.platform)
    machine = platform.machine().lower()
    arch = {"x86_64": "x64", "amd64": "x64", "arm64": "arm64", "aarch64": "arm64"}.get(machine)
    if system is None or arch is None:
        raise UpdateError(f"no prebuilt gg for {sys.platform}/{machine}; build it from source")
    return f"gg-{system}-{arch}" + (".exe" if system == "windows" else "")


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


def replace_running(new: Path, target: Path) -> None:
    """Swap `new` in for `target`, which may be the running program. Windows cannot overwrite or delete a
    running .exe but can rename it, so the old file moves aside (and is deleted by the next update)."""
    if sys.platform == "win32":
        old = target.with_name(target.name + ".old")
        if old.exists():
            old.unlink()
        os.replace(target, old)
        try:
            os.replace(new, target)
        except OSError:
            os.replace(old, target)
            raise
    else:
        os.chmod(new, 0o755)
        os.replace(new, target)


def cleanup_old() -> None:
    exe = installed_binary()
    if exe is not None:
        try:
            exe.with_name(exe.name + ".old").unlink()
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
            new = Path(tmp) / target.name
            _download(assets[wanted], new, wanted)
            if SUMS in assets:
                sums_file = Path(tmp) / SUMS
                _download(assets[SUMS], sums_file, SUMS)
                expect = parse_sums(sums_file.read_text(encoding="utf-8")).get(wanted)
                if expect is None or expect != _sha256(new):
                    raise UpdateError("the downloaded file does not match its SHA-256 in SHA256SUMS.txt; "
                                      "nothing was changed")
            else:
                print("warning: this release has no SHA256SUMS.txt; the download was not verified", file=sys.stderr)
            os.chmod(new, 0o755)
            probe = subprocess.run([str(new), "--version"], capture_output=True, text=True, timeout=120)
            if probe.returncode != 0:
                raise UpdateError("the downloaded gg does not start on this machine; nothing was changed\n"
                                  + probe.stderr.strip())
            replace_running(new, target)
        print(f"gg {latest} is installed at {target}")
        return 0
    except UpdateError as err:
        print(f"Error: {err}", file=sys.stderr)
        return 1
    except (subprocess.SubprocessError, OSError) as err:
        print(f"Error: update failed: {err}", file=sys.stderr)
        return 1
