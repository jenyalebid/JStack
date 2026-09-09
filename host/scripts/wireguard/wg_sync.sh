#!/bin/bash
# Applies peer changes from wg0.conf to the live interface without dropping it.
# Triggered by the hub's sync LaunchDaemon (root, WatchPaths on the conf)
# whenever it changes — pairing a new device needs no sudo and no restart.
set -euo pipefail

WG="${WG:-/opt/homebrew/bin/wg}"
# Both defaults are derived, not literal, for the same reason as in wg_up.sh:
# this file ships to hubs that are not this machine. Installed copies never
# reach them — install_hub.sh writes explicit values into the daemon it makes.
SELF_DIR="$(cd "$(dirname "$0")" && pwd)"
CONF="${WG_CONF:-$SELF_DIR/../../Credentials/wireguard/wg0.conf}"
NAME_FILE="${WG_NAME_FILE:-/var/run/wireguard/jarvis-wg.name}"

[ -s "$NAME_FILE" ] || { echo "wg_sync: tunnel not up (no $NAME_FILE) — nothing to sync"; exit 0; }
IFACE="$(cat "$NAME_FILE")"

"$WG" syncconf "$IFACE" "$CONF"
echo "wg_sync: $CONF -> $IFACE"
