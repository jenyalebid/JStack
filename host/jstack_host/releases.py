"""Mac app releases — the update feed jRemote.app updates itself from.

The Mac app is a thin client of this API and cannot do anything without
reaching it, so the update channel rides the same authenticated connection
rather than standing up a second one. A Mac that can run jRemote at all can
fetch its own updates — on the LAN, through the WireGuard tunnel, from a work
machine, identically, with no public hosting and no separate credentials.

There is exactly one published release at a time. `release-mac.sh` in the app
repo builds it, notarizes it, and publishes here; every Mac picks it up on its
next launch check. Rollback is republishing an older build, which is why the
manifest carries the build number rather than trusting file order.

**A half-published release goes red rather than quiet.** `latest()` raises if
the manifest names a zip that is missing or the wrong size — the app would
otherwise be told "here is an update", download it, fail its own checksum,
and retry forever with nothing on the Mac saying why. A missing manifest is
the one honest empty: nothing has been published yet.

**And "nothing published" is not the same as "nothing is published here."**
Most hosts are not publishers — a standalone host on a laptop or a desktop
serves the same API and has never built anything. Both used to answer the
identical empty, and the app read the empty as "you are up to date", which is
a lie on every Mac that is itself a host: it would sit on an old build
forever, being told by the one machine that cannot know that it is current.
`publishes()` is the difference, and it is the same distinction the rest of
this API already draws for a feature a host does not carry.
"""

import json
from pathlib import Path

from . import hostenv

# state/ is gitignored — a 4 MB signed zip per release is runtime output, not
# source. Same tree as the scheduler's and the usage caps' state.
# Where builds live is the host's answer, not this module's.
RELEASE_DIR = hostenv.releases_dir()
MANIFEST = RELEASE_DIR / "latest.json"

# Every field the publisher must write. A manifest missing any of them is a
# publisher bug, and it surfaces here rather than as a mystery on the laptop.
REQUIRED = ("version", "build", "sha256", "bytes", "file")


class ReleaseError(Exception):
    """The feed is broken — distinct from nothing being published."""


def _read_manifest() -> dict | None:
    """The published manifest, or None if nothing has ever been published."""
    if not MANIFEST.exists():
        return None
    try:
        data = json.loads(MANIFEST.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise ReleaseError(f"release manifest unreadable: {exc}") from exc
    if not isinstance(data, dict):
        raise ReleaseError("release manifest is not an object")
    missing = [k for k in REQUIRED if k not in data]
    if missing:
        raise ReleaseError(f"release manifest missing {', '.join(missing)}")
    return data


def publishes() -> bool:
    """Whether Mac builds are published on this host at all.

    The release dir is made by the publisher (`release-mac.sh`) and by nothing
    else, so its existence is the question answered here: a host that has one
    is a machine builds come from, a host that doesn't is a machine that can
    never have an update to offer. A host that has published and then had its
    manifest removed still counts — it is a broken publisher, which is a
    different thing to say than "not a publisher", and the app says so.
    """
    return RELEASE_DIR.is_dir()


def artifact_path(manifest: dict) -> Path:
    """The zip this manifest describes, resolved inside the release dir.

    `file` is a bare name by construction, but it arrives from disk, so it is
    treated as untrusted: anything that escapes the release dir is a broken
    publish, not a path to follow.
    """
    name = str(manifest["file"])
    path = (RELEASE_DIR / name).resolve()
    if path.parent != RELEASE_DIR.resolve():
        raise ReleaseError(f"release artifact escapes the release dir: {name}")
    return path


def latest() -> dict | None:
    """The published release, verified against what is actually on disk.

    Returns None when nothing has been published. Raises `ReleaseError` when a
    release is claimed but its artifact is missing or the wrong size — the
    difference between "no update" and "the feed is broken" is the whole
    reason this function exists instead of the app reading the file.
    """
    manifest = _read_manifest()
    if manifest is None:
        return None
    path = artifact_path(manifest)
    if not path.exists():
        raise ReleaseError(f"release {manifest['build']} names a missing artifact: {path.name}")
    size = path.stat().st_size
    if size != int(manifest["bytes"]):
        raise ReleaseError(
            f"release {manifest['build']} artifact is {size} bytes, "
            f"manifest says {manifest['bytes']} — half-published?"
        )
    return {
        "version": str(manifest["version"]),
        "build": int(manifest["build"]),
        "sha256": str(manifest["sha256"]),
        "bytes": size,
        "notes": str(manifest.get("notes", "")),
        "published": str(manifest.get("published", "")),
        # Signing identity the client pins the downloaded bundle to. Served
        # rather than hardcoded in the app so rotating the certificate is a
        # host change, not a build every Mac has to already have taken.
        "teamID": str(manifest.get("teamID", "")),
    }
