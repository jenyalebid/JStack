#!/usr/bin/env bash
# JStack installer — a bare machine to a working stack, in one command.
#
#   curl -fsSL https://raw.githubusercontent.com/jenyalebid/JStack/main/install.sh | bash
#   ./install.sh --yes --agent Ada --scheduler       # unattended, everything
#   ./install.sh --dry-run                           # print the plan, touch nothing
#
# Setup used to be six steps across two surfaces, each documented, each failing
# invisibly when skipped. This does all six and then runs `jstack-doctor`, so
# the install ends with a verdict rather than an assumption.
#
# What it will not do: run as root, overwrite a file it did not write, or touch
# anything outside $CHECKOUT, ~/.claude, ~/Agents and the shell profile line it
# appends. Every step is idempotent — running it twice is a no-op with a
# different report, which is what makes it safe to use as an updater.

set -uo pipefail

REPO_URL="${JSTACK_REPO_URL:-https://github.com/jenyalebid/JStack.git}"
CHECKOUT="${JSTACK_CHECKOUT:-$HOME/JStack}"
AGENT_ROOT="${JSTACK_AGENT_ROOT:-$HOME/Agents}"
MIN_PY_MAJOR=3
MIN_PY_MINOR=9

ASSUME_YES=0
DRY_RUN=0
AGENT_NAME=""
WANT_SCHEDULER=0
WANT_CLAUDE=1

usage() {
    cat <<'EOF'
usage: install.sh [options]

  --yes, -y           don't ask; accept every default
  --dry-run           print what would happen and change nothing
  --agent NAME        create this agent workspace (default: ask, or "Main" with --yes)
  --agent-root DIR    where agent workspaces live (default: ~/Agents)
  --checkout DIR      where to clone JStack (default: ~/JStack)
  --scheduler         also install the scheduler daemon as a user service
  --no-claude         don't install Claude Code even if it is missing
  --help, -h          this

Environment: JSTACK_REPO_URL, JSTACK_CHECKOUT, JSTACK_AGENT_ROOT override the
defaults above. JSTACK_ROOT, if you export it, is honoured by everything the
stack does afterwards — see docs/systems/root-derivation.md.
EOF
}

while [ $# -gt 0 ]; do
    case "$1" in
        -y|--yes)      ASSUME_YES=1 ;;
        --dry-run)     DRY_RUN=1 ;;
        --agent)       AGENT_NAME="${2:-}"; shift ;;
        --agent-root)  AGENT_ROOT="${2:-}"; shift ;;
        --checkout)    CHECKOUT="${2:-}"; shift ;;
        --scheduler)   WANT_SCHEDULER=1 ;;
        --no-claude)   WANT_CLAUDE=0 ;;
        -h|--help)     usage; exit 0 ;;
        *)             echo "unknown option: $1" >&2; usage >&2; exit 2 ;;
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

# Everything that changes the machine goes through here, so --dry-run is a
# property of the script rather than a flag each step remembers to check.
run() {
    if [ "$DRY_RUN" = "1" ]; then would "$*"; return 0; fi
    "$@"
}

ask() {
    # $1 prompt, $2 default (y/n). --yes and a non-tty both take the default.
    local reply
    if [ "$ASSUME_YES" = "1" ] || [ ! -t 0 ]; then
        [ "$2" = "y" ]; return
    fi
    printf '  %s [%s] ' "$1" "$([ "$2" = y ] && echo Y/n || echo y/N)"
    read -r reply </dev/tty || reply=""
    reply="${reply:-$2}"
    case "$reply" in [Yy]*) return 0 ;; *) return 1 ;; esac
}

# ── 0. preflight ────────────────────────────────────────────────────────────

step "Checking prerequisites"

[ "$(id -u)" != "0" ] || die "don't run this as root — JStack installs per-user, and a root-owned checkout is a machine only root can fix"

case "$(uname -s)" in
    Darwin|Linux) ok "$(uname -s) $(uname -m)" ;;
    *) die "unsupported platform $(uname -s) — macOS and Linux only" ;;
esac

command -v git >/dev/null 2>&1 || die "no git on PATH — install it first (macOS: xcode-select --install)"
ok "git — $(git --version)"

PY=""
for cand in python3 python3.13 python3.12 python3.11; do
    command -v "$cand" >/dev/null 2>&1 || continue
    if "$cand" -c "import sys; sys.exit(0 if sys.version_info >= ($MIN_PY_MAJOR,$MIN_PY_MINOR) else 1)" 2>/dev/null; then
        PY="$(command -v "$cand")"; break
    fi
done
[ -n "$PY" ] || die "no python3 >= $MIN_PY_MAJOR.$MIN_PY_MINOR on PATH — the scheduler needs zoneinfo, which arrived in 3.9"
ok "python — $("$PY" --version 2>&1) at $PY"

# ── 1. Claude Code ──────────────────────────────────────────────────────────

step "Claude Code"

CLAUDE="$(command -v claude 2>/dev/null || true)"
[ -n "$CLAUDE" ] || [ ! -x "$HOME/.local/bin/claude" ] || CLAUDE="$HOME/.local/bin/claude"

if [ -n "$CLAUDE" ]; then
    ok "already installed — $("$CLAUDE" --version 2>&1 | head -1)"
elif [ "$WANT_CLAUDE" = "0" ]; then
    warn "not installed, and --no-claude was passed — the plugin cannot be registered without it"
elif ask "Claude Code is not installed. Install it now?" y; then
    if [ "$DRY_RUN" = "1" ]; then
        would "curl -fsSL https://claude.ai/install.sh | bash"
    elif curl -fsSL https://claude.ai/install.sh | bash >/tmp/jstack-claude-install.log 2>&1; then
        CLAUDE="$HOME/.local/bin/claude"
        ok "installed — $("$CLAUDE" --version 2>&1 | head -1)"
    else
        warn "the Claude Code installer failed; see /tmp/jstack-claude-install.log"
    fi
else
    warn "skipped — the plugin steps below will be skipped too"
fi

# The installer drops it in ~/.local/bin, which is not on a default PATH.
export PATH="$HOME/.local/bin:$PATH"

# ── 2. the checkout ─────────────────────────────────────────────────────────

step "JStack source at $CHECKOUT"

if [ -d "$CHECKOUT/.git" ]; then
    # An existing checkout is somebody's working tree. Fetch so the install is
    # current, but never reset — an installer that discards local commits is a
    # worse outcome than an installer that is one commit behind.
    run git -C "$CHECKOUT" fetch --quiet origin
    if [ "$DRY_RUN" = "1" ]; then
        would "git -C $CHECKOUT merge --ff-only (if clean)"
    elif [ -z "$(git -C "$CHECKOUT" status --porcelain)" ] && git -C "$CHECKOUT" merge --ff-only --quiet '@{u}' 2>/dev/null; then
        ok "updated to $(git -C "$CHECKOUT" log --oneline -1)"
    else
        warn "left as-is at $(git -C "$CHECKOUT" log --oneline -1) — the tree has local changes or diverged"
    fi
elif [ -e "$CHECKOUT" ]; then
    die "$CHECKOUT exists and is not a git checkout — move it aside or pass --checkout DIR"
else
    run git clone --quiet "$REPO_URL" "$CHECKOUT" || die "clone failed"
    [ "$DRY_RUN" = "1" ] || ok "cloned at $(git -C "$CHECKOUT" log --oneline -1)"
fi

PLUGIN="$CHECKOUT/plugins/jstack"
BIN="$PLUGIN/bin"

# ── 3. the plugin ───────────────────────────────────────────────────────────

step "Registering the plugin"

if [ -z "$CLAUDE" ]; then
    warn "no claude — skipping marketplace registration"
else
    # A directory-source marketplace means the plugin runs FROM the checkout:
    # `git pull` is the update, and there is no versioned cache to go stale.
    if "$CLAUDE" plugin marketplace list 2>/dev/null | grep -q "JStack"; then
        ok "marketplace JStack already registered"
    else
        run "$CLAUDE" plugin marketplace add "$CHECKOUT" >/dev/null 2>&1 \
            && ok "marketplace JStack → $CHECKOUT" \
            || warn "could not register the marketplace"
    fi
    if "$CLAUDE" plugin list 2>/dev/null | grep -q "jstack@JStack"; then
        ok "plugin jstack@JStack already installed"
    else
        run "$CLAUDE" plugin install "jstack@JStack" --config "agent_root=$AGENT_ROOT" >/dev/null 2>&1 \
            && ok "plugin jstack@JStack installed, agent_root=$AGENT_ROOT" \
            || warn "could not install the plugin — run: claude plugin install jstack@JStack"
    fi
fi

# ── 4. an agent workspace ───────────────────────────────────────────────────
#
# The step whose absence looks like the tools being broken: with no agent, every
# seat-aware tool succeeds against nobody. log_event writes for an agent that
# does not exist and the session-end engine reviews nothing — no errors anywhere.

step "Agent workspace"

# Asked of root.py rather than re-derived here: an agent is a directory with a
# CLAUDE.md, or with one immediate subdirectory that has one, and a second
# opinion of that rule is how an installer ends up creating a workspace beside
# three the tools can already see.
existing=""
if [ -d "$AGENT_ROOT" ]; then
    existing="$(JSTACK_AGENTS_DIR="$AGENT_ROOT" PYTHONPATH="$PLUGIN" "$PY" -c \
        'import root; print(" ".join(root.agents()))' 2>/dev/null || true)"
fi

if [ -n "$existing" ]; then
    ok "$AGENT_ROOT already holds agents"
else
    if [ -z "$AGENT_NAME" ]; then
        if [ "$ASSUME_YES" = "1" ] || [ ! -t 0 ]; then
            AGENT_NAME="Main"
        else
            printf '  Name for your first agent workspace [Main]: '
            read -r AGENT_NAME </dev/tty || AGENT_NAME=""
            AGENT_NAME="${AGENT_NAME:-Main}"
        fi
    fi
    seat="$AGENT_ROOT/$AGENT_NAME"
    if [ -f "$seat/CLAUDE.md" ]; then
        ok "$seat/CLAUDE.md already exists"
    else
        run mkdir -p "$seat"
        if [ "$DRY_RUN" = "1" ]; then
            would "write $seat/CLAUDE.md"
        else
            cat > "$seat/CLAUDE.md" <<EOF
# $AGENT_NAME

Who this agent is, and what it owns. JStack reads this file's EXISTENCE to
decide that $seat is an agent workspace — the contents are yours.

Replace everything below.

## What I own

- (the systems, repos or areas this agent is responsible for)

## How I work

- (conventions a session here should follow)
EOF
            ok "created $seat/CLAUDE.md"
        fi
    fi
fi

# ── 5. rules and bare commands ──────────────────────────────────────────────
#
# Claude Code loads both from user scope only, so a plugin cannot deliver them.
# Symlinked, not copied, and pointed at the CHECKOUT — a link into a versioned
# plugin cache works until that version is reaped, then silently points at
# nothing. `jstack-doctor` grades exactly that case as a failure.

step "Rules and bare commands"

link_stage() {
    local src="$1" dst="$2" label="$3" made=0 kept=0
    [ -d "$src" ] || { warn "no $src"; return; }
    run mkdir -p "$dst"
    for f in "$src"/*.md; do
        [ -e "$f" ] || continue
        local target="$dst/$(basename "$f")"
        if [ -e "$target" ] || [ -L "$target" ]; then kept=$((kept+1)); continue; fi
        run ln -s "$f" "$target" && made=$((made+1))
    done
    if [ "$kept" -gt 0 ]; then
        ok "$made $label linked, $kept left alone (already present)"
    else
        ok "$made $label linked into $dst"
    fi
}

link_stage "$PLUGIN/rules-stage"    "$HOME/.claude/rules"    "rules"
link_stage "$PLUGIN/commands-stage" "$HOME/.claude/commands" "bare commands"

# ── 6. bin on PATH ──────────────────────────────────────────────────────────

step "Adapters on PATH"

case "${SHELL:-}" in
    */zsh)  PROFILE="$HOME/.zshrc" ;;
    */bash) PROFILE="$HOME/.bash_profile" ;;
    *)      PROFILE="$HOME/.profile" ;;
esac
LINE="export PATH=\"$BIN:\$PATH\"  # jstack"

if command -v log_event >/dev/null 2>&1; then
    ok "already reachable — $(command -v log_event)"
elif [ -f "$PROFILE" ] && grep -qF "$BIN" "$PROFILE" 2>/dev/null; then
    ok "$PROFILE already has it — open a new shell to pick it up"
elif ask "Add $BIN to PATH in $PROFILE?" y; then
    if [ "$DRY_RUN" = "1" ]; then
        would "append to $PROFILE: $LINE"
    else
        printf '\n%s\n' "$LINE" >> "$PROFILE"
        ok "appended to $PROFILE — open a new shell, or: source $PROFILE"
    fi
else
    warn "skipped — log_event, msg and schedule-self stay unreachable by bare name"
fi
export PATH="$BIN:$PATH"

# ── 7. the scheduler daemon (optional) ──────────────────────────────────────
#
# Booking and firing are different halves. Without a daemon the registry accepts
# a job, `list` shows it, and the hour passes in silence.

step "Scheduler daemon"

if [ "$WANT_SCHEDULER" = "1" ] || ask "Install the scheduler daemon as a user service? (needed for recurring wakes)" n; then
    if [ "$DRY_RUN" = "1" ]; then
        would "$BIN/jstack-scheduler install"
    else
        "$PY" "$BIN/jstack-scheduler" install && ok "daemon installed" || warn "daemon install reported a problem"
    fi
else
    note "skipped — run \`jstack-scheduler install\` any time"
fi

# ── 8. the verdict ──────────────────────────────────────────────────────────

step "Verifying"

if [ "$DRY_RUN" = "1" ]; then
    would "$BIN/jstack-doctor"
    printf '\n%sdry run — nothing was changed%s\n' "$B" "$Z"
    exit 0
fi

echo
"$PY" "$BIN/jstack-doctor"
rc=$?

echo
case "$rc" in
    0) printf '%sJStack is installed and every check passed.%s\n' "$GRN$B" "$Z" ;;
    1) printf '%sJStack is installed and working.%s The warnings above are capabilities\nthat stay absent until you add them — normal on a fresh machine.\n' "$GRN$B" "$Z" ;;
    *) printf '%sInstalled, but something above is broken.%s Each failure names its fix;\nre-run `jstack-doctor` after each one.\n' "$YEL$B" "$Z" ;;
esac

cat <<EOF

Next: open a new shell so PATH takes effect, then start a session inside an
agent workspace —

    cd $AGENT_ROOT/${AGENT_NAME:-<agent>}
    claude

and run /jstack:work on any topic. Re-run this script any time to update;
it changes only what has drifted.
EOF

exit 0
