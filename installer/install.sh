#!/bin/sh
# Greengold installer for Linux and macOS. No Python needed.
#   curl -fsSL https://raw.githubusercontent.com/Greengold-Lang/greengold-lang/main/installer/install.sh | sh
# Options (environment): GG_VERSION=0.3.3 (default: latest), GG_INSTALL_DIR=~/.greengold/bin, GG_NO_MODIFY_PATH=1
set -eu

REPO="${GG_REPO:-Greengold-Lang/greengold-lang}"
INSTALL_DIR="${GG_INSTALL_DIR:-$HOME/.greengold/bin}"

say() { printf '%s\n' "$*"; }
die() { printf 'error: %s\n' "$*" >&2; exit 1; }

case "$(uname -s)" in
  Linux)  os=linux ;;
  Darwin) os=macos ;;
  *) die "unsupported OS $(uname -s); on Windows use install.ps1" ;;
esac
case "$(uname -m)" in
  x86_64|amd64)  arch=x64 ;;
  arm64|aarch64) arch=arm64 ;;
  *) die "unsupported CPU $(uname -m)" ;;
esac
if [ "$os" = macos ] && [ "$arch" = x64 ] && [ "$(sysctl -n hw.optional.arm64 2>/dev/null || echo 0)" != 1 ]; then
  die "there is no prebuilt gg for Intel Macs; install from source: pip install -e . (see the README)"
fi
# A shell under Rosetta reports x86_64 on an Apple Silicon Mac; prefer the native build.
if [ "$os" = macos ] && [ "$arch" = x64 ] && [ "$(sysctl -n hw.optional.arm64 2>/dev/null || echo 0)" = 1 ]; then
  arch=arm64
fi
asset="gg-$os-$arch.tar.gz"

if [ -n "${GG_VERSION:-}" ]; then
  base="https://github.com/$REPO/releases/download/v${GG_VERSION#v}"
else
  base="https://github.com/$REPO/releases/latest/download"
fi

if command -v curl >/dev/null 2>&1; then
  fetch() { curl -fsSL "$1" -o "$2"; }
elif command -v wget >/dev/null 2>&1; then
  fetch() { wget -q "$1" -O "$2"; }
else
  die "curl or wget is required"
fi

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

say "Downloading $asset ..."
fetch "$base/$asset" "$tmp/$asset" || die "download failed: $base/$asset"

if fetch "$base/SHA256SUMS.txt" "$tmp/SHA256SUMS.txt" 2>/dev/null; then
  want="$(awk -v a="$asset" '$2 == a || $2 == "*" a { print $1; exit }' "$tmp/SHA256SUMS.txt")"
  if command -v sha256sum >/dev/null 2>&1; then got="$(sha256sum "$tmp/$asset" | awk '{print $1}')"
  else got="$(shasum -a 256 "$tmp/$asset" | awk '{print $1}')"; fi
  if [ -z "$want" ] || [ "$want" != "$got" ]; then die "checksum mismatch; nothing was installed"; fi
else
  say "warning: no SHA256SUMS.txt for this release; skipping verification"
fi

mkdir -p "$INSTALL_DIR"
mkdir "$tmp/new"
tar -xzf "$tmp/$asset" -C "$tmp/new" || die "cannot unpack $asset"
"$tmp/new/gg" --version >/dev/null 2>&1 || die "the downloaded gg does not run on this machine"
rm -rf "$INSTALL_DIR/_internal" "$INSTALL_DIR/.gg-old"
cp -Rp "$tmp/new/." "$INSTALL_DIR/"
say "Installed $("$INSTALL_DIR/gg" --version | head -n 1) to $INSTALL_DIR/gg"

case ":$PATH:" in
  *":$INSTALL_DIR:"*) on_path=1 ;;
  *) on_path=0 ;;
esac

if [ "$on_path" = 0 ] && [ -z "${GG_NO_MODIFY_PATH:-}" ]; then
  line="export PATH=\"$INSTALL_DIR:\$PATH\""
  added=""
  # The login shell's own rc file is created if missing; others are only extended if they exist.
  case "${SHELL:-}" in
    */zsh)  own="$HOME/.zshrc" ;;
    */bash) own="$HOME/.bashrc" ;;
    *)      own="$HOME/.profile" ;;
  esac
  for rc in "$own" "$HOME/.zshrc" "$HOME/.bashrc" "$HOME/.profile"; do
    [ "$rc" = "$own" ] || [ -f "$rc" ] || continue
    if ! grep -qsF "$INSTALL_DIR" "$rc"; then
      printf '\n# Greengold\n%s\n' "$line" >> "$rc"
      added="$added $rc"
    fi
  done
  fishconf="$HOME/.config/fish/config.fish"
  if [ -f "$fishconf" ] && ! grep -qsF "$INSTALL_DIR" "$fishconf"; then
    printf '\n# Greengold\nfish_add_path "%s"\n' "$INSTALL_DIR" >> "$fishconf"
    added="$added $fishconf"
  fi
  if [ -n "$added" ]; then say "Added $INSTALL_DIR to PATH in:$added"; fi
  say "Open a new terminal (or run: $line) and try:  gg --version"
else
  say "Try:  gg --version"
fi
say "Update later with:  gg update"
