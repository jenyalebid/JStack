#!/bin/bash
# Endpoint re-resolve for a leaf tunnel — run every 2 min by launchd
# (com.jremote.leaf-watch, root, StartInterval).
#
# A leaf dials the hub by DNS name, but WireGuard resolves that name once, at
# setconf time. When the hub's home IP changes (DDNS moves the record), the
# leaf keeps sending to the dead address forever — the tunnel is up, the
# process is healthy, and nothing arrives. So: if the handshake has gone
# stale, re-set the peer's endpoint, which makes wg resolve the name again.
# Re-setting while the hub is genuinely unreachable is a DNS query and a
# no-op, so firing on "stale" needs no better evidence than stale.
#
# Every binary and path is env-overridable so the integration test can run
# this unprivileged against mocks.
set -euo pipefail

WG="${WG:-/opt/homebrew/bin/wg}"
CONF="${WG_CONF:-/etc/wireguard/jrleaf.conf}"
NAME_FILE="${WG_NAME_FILE:-/var/run/wireguard/jremote-wg.name}"
STALE_SECS="${WG_STALE_SECS:-150}"

[ -s "$NAME_FILE" ] || { echo "leaf_watch: tunnel not up (no $NAME_FILE) — nothing to do"; exit 0; }
IFACE="$(cat "$NAME_FILE")"

PUB="$(sed -n 's/^PublicKey *= *//p' "$CONF" | head -1)"
ENDPOINT="$(sed -n 's/^Endpoint *= *//p' "$CONF" | head -1)"
[ -n "$PUB" ] && [ -n "$ENDPOINT" ] || { echo "leaf_watch: $CONF has no peer endpoint" >&2; exit 1; }

LAST="$("$WG" show "$IFACE" latest-handshakes | awk -v pub="$PUB" '$1 == pub {print $2}')"
NOW="$(date +%s)"
if [ -z "$LAST" ] || [ "$LAST" -eq 0 ] || [ $((NOW - LAST)) -gt "$STALE_SECS" ]; then
    "$WG" set "$IFACE" peer "$PUB" endpoint "$ENDPOINT"
    echo "leaf_watch: handshake stale — endpoint re-set to $ENDPOINT"
fi
