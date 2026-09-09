#!/usr/bin/env bash
# jRemote host installer — a Mac you can reach from your phone, in one command.
#
#   curl -fsSL https://raw.githubusercontent.com/jenyalebid/JStack/main/host/install.sh | bash
#   ./install.sh --port 9090 --yes         # from a checkout, unattended
#   ./install.sh --dry-run                 # print the plan, touch nothing
#   ./install.sh --update                  # pull, reinstall, restart
#   ./install.sh --uninstall               # take it back off
#
# What it does, and nothing else: clone (or update) the JStack checkout, build a
# private virtualenv beside the package, install the host into it, and register
# a **user** LaunchAgent so the host survives a logout and a reboot.
#
# It never asks for a password. No `sudo`, no root, nothing written outside
# your own home directory — an install that needs an admin password is one you
# have to trust rather than read, and this is a program that watches your
# terminal sessions. Everything it runs is in this repository.
#
# What it will not do: run as root, install into a Python it does not own, or
# overwrite a host that is already answering unless you say --force. Every step
# is idempotent — running it twice is an upgrade, which is what makes it safe
# to use as the updater.

set -uo pipefail

REPO_URL="${JSTACK_REPO_URL:-https://github.com/jenyalebid/JStack.git}"
CHECKOUT="${JSTACK_CHECKOUT:-$HOME/JStack}"
BIN_DIR="${JSTACK_BIN_DIR:-$HOME/.local/bin}"
MIN_PY_MAJOR=3
MIN_PY_MINOR=11

ASSUME_YES=0
DRY_RUN=0
DO_UPDATE=0
DO_UNINSTALL=0
FORCE=0
PORT=9090
BIND="0.0.0.0"
STATE_DIR=""

usage() {
    cat <<'EOF'
usage: install.sh [options]

  --yes, -y          don't ask; accept every default
  --dry-run          print what would happen and change nothing
  --update           git pull the checkout, reinstall, restart the host
  --uninstall        remove the LaunchAgent (your state and token stay)
  --port N           port to serve on (default 9090)
  --bind ADDR        bind address (default 0.0.0.0 — see below)
  --state-dir DIR    where this host keeps its state
                     (default ~/.local/state/jremote)
  --force            install even if something already answers on the port
  --checkout DIR     where to clone JStack (default ~/JStack)
  --help, -h         this

The default bind is 0.0.0.0 on purpose: a host is reached over a tunnel or
across your LAN, and one bound to 127.0.0.1 is a host only this Mac can see.
Every route requires the bearer token; /api/health is the one exception and
says nothing about what is on the machine.
EOF
}

while [ $# -gt 0 ]; do
    case "$1" in
        -y|--yes)     ASSUME_YES=1 ;;
        --dry-run)    DRY_RUN=1 ;;
        --update)     DO_UPDATE=1 ;;
        --uninstall)  DO_UNINSTALL=1 ;;
        --force)      FORCE=1 ;;
        --port)       PORT="${2:-}"; shift ;;
        --bind)       BIND="${2:-}"; shift ;;
        --state-dir)  STATE_DIR="${2:-}"; shift ;;
        --checkout)   CHECKOUT="${2:-}"; shift ;;
        -h|--help)    usage; exit 0 ;;
        *)            echo "unknown option: $1" >&2; usage >&2; exit 2 ;;
    esac
    shift
done

# ── output ──────────────────────────────────────────────────────────────────

if [ -t 1 ]; then B=$'\033[1m'; DIM=$'\033[2m'; RED=$'\033[31m'; GRN=$'\033[32m'; YEL=$'\033[33m'; Z=$'\033[0m'
else B=""; DIM=""; RED=""; GRN=""; YEL=""; Z=""; fi

step()  { printf '\n%s==>%s %s\n' "$B" "$Z" "$1"; }
ok()    { printf '  %sok%s   %s\n' "$GRN" "$Z" "$1"; }
warn()  { printf '  %swarn%s %s\n' "$YEL" "$Z" "$1"; }
die()   { printf '  %sfail%s %s\n' "$RED" "$Z" "$1" >&2; exit 1; }
note()  { printf '  %s%s%s\n' "$DIM" "$1" "$Z"; }
would() { printf '  %swould%s %s\n' "$DIM" "$Z" "$1"; }

run() {
    if [ "$DRY_RUN" = "1" ]; then would "$*"; return 0; fi
    "$@"
}

# `ok` for a fact this script observed; `did` for the result of an action it
# took. In a dry run no action was taken, so `did` says nothing — an "ok
# installed" printed by --dry-run is a check reporting state it cannot observe,
# which is worse than printing nothing at all.
did() { [ "$DRY_RUN" = "1" ] || ok "$1"; }

# ── 0. preflight ────────────────────────────────────────────────────────────

step "Checking prerequisites"

[ "$(id -u)" != "0" ] || die "don't run this as root — the host installs per-user, and a root-owned host is one only root can remove"
[ "$(uname -s)" = "Darwin" ] || die "this installs a macOS LaunchAgent; $(uname -s) is not supported"
ok "macOS, running as $(id -un)"

# The interpreter that builds the venv is the one the LaunchAgent will run
# forever, so it is picked deliberately rather than taken from whatever `python3`
# resolves to in this shell. Homebrew first: the system python3 at
# /usr/bin/python3 is Apple's, gets replaced by OS updates, and has taken a
# venv's packages with it before.
PY=""
for cand in /opt/homebrew/bin/python3 /usr/local/bin/python3 "$(command -v python3 2>/dev/null)"; do
    [ -n "$cand" ] && [ -x "$cand" ] || continue
    if "$cand" -c "import sys; raise SystemExit(0 if sys.version_info[:2] >= ($MIN_PY_MAJOR, $MIN_PY_MINOR) else 1)" 2>/dev/null; then
        PY="$cand"; break
    fi
done
[ -n "$PY" ] || die "need Python ${MIN_PY_MAJOR}.${MIN_PY_MINOR}+ — install it with \`brew install python3\` and re-run"
ok "python $("$PY" -c 'import platform;print(platform.python_version())') at $PY"

command -v git >/dev/null 2>&1 || die "git is required — install the Xcode command line tools with \`xcode-select --install\`"
ok "git $(git --version | awk '{print $3}')"

# ── 1. the checkout ─────────────────────────────────────────────────────────
#
# Where the host runs from, permanently. The LaunchAgent points at this
# directory rather than at a copy: nothing is unpacked into a cache, so
# `git pull` here IS the update, and there is exactly one tree to read if you
# want to know what is running on your machine.

step "Getting the source"

# Running from inside a checkout already? Then that is the checkout — cloning a
# second one and installing *that* is how someone ends up editing a tree the
# host never reads.
SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd 2>/dev/null || true)"
if [ -n "$SELF_DIR" ] && [ -f "$SELF_DIR/pyproject.toml" ] && [ -d "$SELF_DIR/jstack_host" ]; then
    HOST_DIR="$SELF_DIR"
    CHECKOUT="$(cd "$SELF_DIR/.." && pwd)"
    ok "using this checkout — $CHECKOUT"
    if [ "$DO_UPDATE" = "1" ] && [ -d "$CHECKOUT/.git" ]; then
        run git -C "$CHECKOUT" pull --ff-only || warn "git pull did not fast-forward; installing what is here"
    fi
elif [ -d "$CHECKOUT/.git" ]; then
    HOST_DIR="$CHECKOUT/host"
    ok "checkout already at $CHECKOUT"
    run git -C "$CHECKOUT" pull --ff-only || warn "git pull did not fast-forward; installing what is here"
else
    HOST_DIR="$CHECKOUT/host"
    note "cloning $REPO_URL"
    run git clone --depth 1 "$REPO_URL" "$CHECKOUT" || die "clone failed"
    did "cloned to $CHECKOUT"
fi

if [ "$DRY_RUN" != "1" ]; then
    [ -f "$HOST_DIR/pyproject.toml" ] || die "no host package at $HOST_DIR"
fi

# ── 2. the virtualenv ───────────────────────────────────────────────────────
#
# Its own venv, beside the package. Never a `pip install --user` and never
# `--break-system-packages`: this host has real dependencies (FastAPI, uvicorn)
# and installing them into a Python shared with the rest of your machine is how
# an unrelated `pip install` takes your host down months later.

step "Building the environment"

VENV="$HOST_DIR/.venv"
if [ -x "$VENV/bin/python3" ]; then
    ok "virtualenv already at $VENV"
else
    run "$PY" -m venv "$VENV" || die "could not create a virtualenv at $VENV"
    did "virtualenv at $VENV"
fi

run "$VENV/bin/python3" -m pip install --quiet --upgrade pip >/dev/null 2>&1
if ! run "$VENV/bin/python3" -m pip install --quiet -e "$HOST_DIR"; then
    die "pip install failed — the output above says why (no network is the usual one)"
fi
did "jstack-host installed into the virtualenv"

HOSTBIN="$VENV/bin/jstack-host"
if [ "$DRY_RUN" != "1" ]; then
    [ -x "$HOSTBIN" ] || die "pip finished but $HOSTBIN is missing"
fi

# ── 3. the command on PATH ──────────────────────────────────────────────────
#
# A symlink rather than a shell alias or a PATH edit to the venv: the venv is
# an implementation detail that may be rebuilt, and `jstack-host` is the name
# the documentation, the errors and the app's own instructions all use.

step "Putting jstack-host on your PATH"

run mkdir -p "$BIN_DIR"
run ln -sf "$HOSTBIN" "$BIN_DIR/jstack-host"
did "$BIN_DIR/jstack-host"

case ":$PATH:" in
    *":$BIN_DIR:"*) ok "$BIN_DIR is already on your PATH" ;;
    *) warn "$BIN_DIR is not on your PATH — add this to your shell profile:"
       note "export PATH=\"\$HOME/.local/bin:\$PATH\"" ;;
esac

# ── 4. uninstall, if that is what was asked ─────────────────────────────────

if [ "$DO_UNINSTALL" = "1" ]; then
    step "Removing the host"
    run "$HOSTBIN" uninstall
    printf '\n%sThe host is off this Mac.%s Your state and token were left in place,\n' "$B" "$Z"
    printf 'so reinstalling brings the same instance back rather than a new one.\n'
    exit 0
fi

# ── 5. the LaunchAgent ──────────────────────────────────────────────────────

step "Installing the host"

ARGS=(install --port "$PORT" --bind "$BIND")
[ -n "$STATE_DIR" ] && ARGS+=(--state-dir "$STATE_DIR")
[ "$FORCE" = "1" ] && ARGS+=(--force)

if [ "$DRY_RUN" = "1" ]; then
    would "$HOSTBIN ${ARGS[*]}"
    printf '\n%sDry run — nothing was changed.%s\n' "$B" "$Z"
    exit 0
fi

if ! "$HOSTBIN" "${ARGS[@]}"; then
    printf '\n%sThe host did not come up.%s The message above says why. Once it is\n' "$RED$B" "$Z"
    printf 'fixed, re-run this script — it is an upgrade, not a second install.\n'
    exit 1
fi

# ── 6. pairing ──────────────────────────────────────────────────────────────
#
# The last mile, and the one people get stuck on: the host is up and the app
# still has to be told about it. A code rather than the raw token — it expires,
# it names the device before the device connects, and revoking it later does
# not re-key everything else.

step "Pairing"

DEVICE_NAME="${JSTACK_DEVICE_NAME:-My device}"
if "$HOSTBIN" pair "$DEVICE_NAME"; then
    :
else
    warn "could not mint a pairing code — run \`jstack-host pair\` yourself"
fi

cat <<EOF

${B}Your Mac is a jRemote host.${Z}

  jstack-host status      is it up
  jstack-host doctor      what is missing, and how to fix each thing
  jstack-host pair NAME   another code, for another device
  jstack-host where       every path this host resolves

  $0 --update             take new code
  $0 --uninstall          take it back off
EOF
