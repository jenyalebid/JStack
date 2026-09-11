#!/usr/bin/env bash
# Stand a real jRemote host up in a throwaway VM and run the live suite at it.
#
# The in-process suite proves the code; this proves the *product*. It installs
# from a git checkout the way a stranger would, mints a device token the way the
# app does, and then calls every route the host serves over a real socket from a
# machine that is not the host. The coverage gate in tests-live/test_zz_coverage.py
# is what makes "every action" checkable rather than claimed.
#
#   live-vm-test.sh [--vm NAME] [--ref GIT_REF] [--keep] [--reset]
#
#   --vm NAME     guest to use (default: live-actions)
#   --ref REF     branch/tag/sha of THIS repo to install (default: the working tree)
#   --reset       throw the guest away and clone a fresh one first
#   --keep        leave the guest running afterwards (default: leave it running)
#
# Why a VM and not this Mac: the suite opens sessions, writes files and revokes
# devices. tests-live/conftest.py refuses a base URL that resolves to the machine
# running it, so pointing this at production fails closed rather than wiping the
# board someone is looking at.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
HOST_DIR="$REPO_ROOT/host"
VM_SH="${VM_SH:-$HOME/Operations/Infrastructure/scripts/vm.sh}"

VM_NAME="live-actions"
GIT_REF=""
DO_RESET=0

while [ $# -gt 0 ]; do
    case "$1" in
        --vm)    VM_NAME="$2"; shift 2 ;;
        --ref)   GIT_REF="$2"; shift 2 ;;
        --reset) DO_RESET=1; shift ;;
        --keep)  shift ;;
        *) echo "unknown argument: $1" >&2; exit 2 ;;
    esac
done

say() { printf '\033[1m%s\033[0m\n' "$*"; }
die() { printf '\033[31m✗ %s\033[0m\n' "$*" >&2; exit 1; }

[ -x "$VM_SH" ] || die "no vm.sh at $VM_SH — see ~/Systems/vm/SYSTEM.md"

if [ "$DO_RESET" = "1" ]; then
    say "resetting $VM_NAME to a pristine clone"
    "$VM_SH" reset "$VM_NAME"
else
    "$VM_SH" up "$VM_NAME" >/dev/null 2>&1 || true
fi

IP="$("$VM_SH" ip "$VM_NAME" | tail -1 | tr -d '[:space:]')"
[ -n "$IP" ] || die "$VM_NAME has no address — is it booted?"
say "guest $VM_NAME at $IP"

vssh() { "$VM_SH" ssh "$VM_NAME" "$@"; }

# ── dependencies the host installer requires ──
# The base guest ships Python 3.9.6 and no tmux; the installer needs 3.11+ and
# refuses to start chats without tmux. Both are idempotent, so a re-run on a
# guest that already has them costs a few seconds rather than ten minutes.
say "installing python3.12 + tmux in the guest (slow on a pristine guest)"
vssh 'command -v tmux >/dev/null 2>&1 || /opt/homebrew/bin/brew install -q tmux' || \
    die "could not install tmux in the guest"
vssh '/opt/homebrew/bin/brew list python@3.12 >/dev/null 2>&1 || /opt/homebrew/bin/brew install -q python@3.12' || \
    die "could not install python3.12 in the guest"

# ── the checkout the guest installs from ──
# Default is THIS working tree, copied in: the point of the run is usually to
# prove the code in front of you, and a --ref that silently tested `production`
# instead would be the worst kind of green.
if [ -n "$GIT_REF" ]; then
    say "guest clones $GIT_REF from the public repo"
    vssh "rm -rf ~/jStack && git clone --depth 1 -b '$GIT_REF' https://github.com/jenyalebid/jStack.git ~/jStack" || \
        die "clone failed"
else
    say "copying this working tree into the guest"
    vssh 'rm -rf ~/jStack && mkdir -p ~/jStack'
    "$VM_SH" cp "$VM_NAME" "$HOST_DIR" '~/jStack/host' || die "copy failed"
fi

# ── install the host ──
say "running host/install.sh in the guest"
vssh 'bash ~/jStack/host/install.sh --yes 2>&1 | tail -25' || \
    die "host install failed — see the output above"

# ── prove it is listening, then mint a device token the way the app does ──
say "waiting for the host to answer"
for _ in $(seq 1 30); do
    if curl -fsS -m 3 "http://$IP:9090/api/health" >/dev/null 2>&1; then break; fi
    sleep 2
done
curl -fsS -m 5 "http://$IP:9090/api/health" >/dev/null || \
    die "host is not answering on http://$IP:9090 — check \`$VM_SH ssh $VM_NAME\`"

say "minting a device token for the suite"
TOKEN="$(vssh 'cd ~/jStack/host && ./.venv/bin/python3 -c "
import sys; sys.path.insert(0, \".\")
from jstack_host import devices
print(devices.internal_token())
"' | tail -1 | tr -d '[:space:]')"
[ -n "$TOKEN" ] || die "could not mint a device token in the guest"

# ── run the suite from THIS machine, against the guest ──
# From here, not inside the guest: half of what is being proven is that a second
# machine can reach the advertised addresses, and a suite running on the host
# would pass that on loopback without ever leaving the box.
say "running the live suite against http://$IP:9090"
cd "$HOST_DIR"
JREMOTE_LIVE_URL="http://$IP:9090" \
JREMOTE_LIVE_TOKEN="$TOKEN" \
    ./.venv/bin/python3 -m pytest tests-live/ -v --tb=short "$@"
