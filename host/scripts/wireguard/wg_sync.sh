#!/bin/bash
# Applies peer changes from wg0.conf to the live interface without dropping it.
# Triggered by the hub's sync LaunchDaemon (root, WatchPaths on the conf)
# whenever it changes — pairing a new device needs no sudo and no restart.
set -euo pipefail

WG="${WG:-/opt/homebrew/bin/wg}"
# Three rungs, and the middle one is the fix: `WG_CONF` (what install_hub.sh
# writes into this daemon's plist) wins, then `WG_PEER_DIR` — the variable
# `wg_peer.py` honours, so a relocated mesh moves its readers with it — then the
# derivation, which is what a checkout run by hand resolves. Without the middle
# rung this file syncs the tree's conf while the pairing tool writes another.
SELF_DIR="$(cd "$(dirname "$0")" && pwd)"
CONF="${WG_CONF:-${WG_PEER_DIR:-$SELF_DIR/../../Credentials/wireguard}/wg0.conf}"
NAME_FILE="${WG_NAME_FILE:-/var/run/wireguard/jremote-wg.name}"

[ -s "$NAME_FILE" ] || { echo "wg_sync: tunnel not up (no $NAME_FILE) — nothing to sync"; exit 0; }
IFACE="$(cat "$NAME_FILE")"

"$WG" syncconf "$IFACE" "$CONF"
echo "wg_sync: $CONF -> $IFACE"
