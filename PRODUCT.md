# jStack

One Mac runs your AI coding sessions. Every device you own can see them and
drive them.

## What it is

The stack is the **host**: the `jstack-host` process plus its menu-bar app.
Sessions, the scheduler, the integrations, the base commands — that is
jStack, and all of it must work on its own. **jRemote** (iOS/macOS) is a
client for it, not the product: use it, use iTerm, or build your own UI
against the same host.

## The three modes

A freshly installed hub works on its local network. From there its owner
picks how far it reaches:

- **Local** — same-wifi only. The default; nothing to set up beyond install.
- **Open** — an independent hub reachable off-network on its own. Requires a
  port forward; the product's job is to make that setup guided and obvious,
  not to hide it.
- **Managed** — a hub attached to a parent hub (a *leaf* is exactly this: a
  managed hub). Every device connected to the parent reaches the managed
  machine with no extra setup. A managed machine trades independence for
  being managed.

The mode must be visible, and attaching to a parent must be an action that
exists in the UI — not archaeology.

## Installation

Run the script → specify the root → it downloads the app → the app
auto-connects locally → a working session is on screen. That chain is the
product's first impression and it is the bar, end to end.

## Pairing

- The menu bar owns devices: the list of paired devices, with remove, lives
  in the menu-bar app — not in jRemote.
- Pair a Device shows **one address** and a QR code. Phone side: open the
  app, tap the QR button, scan, connected. Nothing else.
- Manual fallback stays: that one address plus the code, typed by hand, for
  a device with no camera.

## Use cases

- Watch and answer a session from the couch, phone in hand.
- Kick off work, leave the house, keep driving it (open or managed hub).
- Pair a new phone in one scan at the menu bar.
- Attach a new Mac as a managed hub; every device already paired to the
  parent just sees it.
- Hand the install command to a friend; they get a working stack on their
  own Mac with zero help from us.

## Featureset

**Host** (`jstack-host`)
- Sessions, board, scheduler, integrations, base commands.
- Enrolment: single-use short-lived codes; one address + QR.
- Mode: local / open / managed — visible, switchable.
- `doctor` self-checks; `where` paths; relocatable root; `--purge` removal.

**Menu bar** (JStack Host app)
- Host start/stop, run-at-login, settings.
- Pair a Device (one address + QR), the device list, device removal.
- Shows the hub's mode.

**jRemote** (iOS + macOS, optional client)
- Sessions, board, multiple hubs; tap-QR-to-scan pairing; passcode lock.
- Mac build self-updates; iOS ships through TestFlight.

**Install**
- One script: root specified, app downloaded, local auto-connect, session
  launched.
- Versioned GitHub releases; a release gate blocks pushes that would leave
  installs running stale code.

## The bar — what "works" means

- Clean macOS, one script: stack installed, app connected, and the launched
  session is a live working session — never a blank thread.
- A phone pairs by one QR scan on the first try, in under a minute.
- An open hub is reachable off-network after following its guided setup.
- A managed hub is reachable by all of its parent's devices with zero
  per-device setup.
- `--purge` leaves nothing behind.
- Every released fix provably reaches every install on its next update.
- An outside install meets all of the above with nobody from the project in
  the loop.

---

Requirements and defects are GitHub issues; a release is a milestone that
closes them. Status lives in issues and `jstack-host doctor`, never here.
This file changes only in the PR that changes the product.
