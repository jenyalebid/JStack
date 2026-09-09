#!/usr/bin/env bash
# JStack installer — a bare machine to a working stack, in one command.
#
#   curl -fsSL https://raw.githubusercontent.com/jenyalebid/JStack/main/install.sh | bash
#   ./install.sh --yes --agent Ada                   # unattended, everything
#   ./install.sh --dry-run                           # print the plan, touch nothing
#
# Setup used to be seven steps across two surfaces, each documented, each
# failing invisibly when skipped. This does all seven and then runs
# `jstack-doctor`, so the install ends with a verdict rather than an assumption.
#
# What it will not do: run as root, overwrite a file it did not write, or touch
# anything outside $CHECKOUT, ~/.claude, ~/Agents, ~/Applications and the shell
# profile line it appends. Every step is idempotent — running it twice is a
# no-op with a different report, which is what makes it safe as an updater.

set -uo pipefail

REPO_URL="${JSTACK_REPO_URL:-https://github.com/jenyalebid/JStack.git}"
CHECKOUT="${JSTACK_CHECKOUT:-$HOME/JStack}"
AGENT_ROOT="${JSTACK_AGENT_ROOT:-$HOME/Agents}"
MIN_PY_MAJOR=3
MIN_PY_MINOR=9

ASSUME_YES=0
DRY_RUN=0
AGENT_NAME=""
WANT_SCHEDULER=1
WANT_CLAUDE=1
WANT_HOST=1
WANT_MENUBAR=1
WANT_APP=1
DECLARE_ROOT=0
LAST_LOG=""
LAST_ELAPSED=""

usage() {
    cat <<'EOF'
usage: install.sh [options]

  --yes, -y           don't ask; accept every default
  --dry-run           print what would happen and change nothing
  --root DIR          root for Agents, Logs, Config, State, Credentials
  --agent NAME        create this agent workspace (default: ask, or "Main" with --yes)
  --agent-root DIR    where agent workspaces live (default: <root>/Agents)
  --checkout DIR      where to clone JStack (default: ~/JStack)
  --no-scheduler      don't install the scheduler daemon (no recurring wakes)
  --no-claude         don't install Claude Code even if it is missing
  --no-host           don't install the host (no remote access, no icon)
  --no-menubar        install the host but not its menu bar icon
  --no-app            don't install the Mac app
  --help, -h          this

The install asks two things — where the root goes and what to call the first
agent workspace — and then runs to the end. Every other part of the stack has
one sensible answer, so it is installed, and the way to decline it is a flag
above rather than a prompt.

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
        --root)        JSTACK_ROOT="${2:-}"; shift ;;
        --scheduler)   WANT_SCHEDULER=1 ;;   # back-compat: it is the default now
        --no-scheduler) WANT_SCHEDULER=0 ;;
        --no-claude)   WANT_CLAUDE=0 ;;
        --no-host)     WANT_HOST=0 ;;
        --no-menubar)  WANT_MENUBAR=0 ;;
        --no-app)      WANT_APP=0 ;;
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

# Is there a human at a terminal to answer a question?
#
# NOT `[ -t 0 ]`. The documented way to run this is `curl … | bash`, which
# makes stdin the pipe carrying the script itself — never a tty, no matter who
# is sitting there. Testing stdin therefore silently turned every question in
# this installer into its default for the one invocation the README teaches:
# the workspace path was stamped as ~/Agents/Main without asking, the scheduler
# was skipped without offering, and the install ended by telling the operator
# to go run the thing it had just decided not to run.
#
# /dev/tty is the controlling terminal regardless of what stdin is piped from,
# which is exactly the question being asked. Absent — cron, a Docker build, a
# CI step — it cannot be opened, and defaults are right.
interactive() {
    [ "$ASSUME_YES" = "1" ] && return 1
    [ -r /dev/tty ] && [ -w /dev/tty ] || return 1
    # Readable and writable is not the same as attached: a detached process
    # keeps the device node and fails at open. Prove it by opening it.
    { : >/dev/tty; } 2>/dev/null || return 1
    return 0
}

# Free-text answer with a default. $1 prompt, $2 default.
#
# The only kind of question this installer asks. There is deliberately no
# yes/no helper: a y/n prompt is an offer, and every offer this script used to
# make had one answer that worked and one that produced a green install missing
# a part. Those are flags now.
ask_value() {
    local reply
    if ! interactive; then printf '%s' "$2"; return; fi
    printf '  %s [%s]: ' "$1" "$2" >/dev/tty
    read -r reply </dev/tty || reply=""
    printf '%s' "${reply:-$2}"
}

# A long step that would otherwise look hung. Runs the command with its output
# in a log, prints elapsed seconds in place, and leaves one line behind.
#
# The Claude Code download, the clone and the host's wheel build are minutes
# each with nothing on screen; silence for that long reads as a hang, and the
# operator's next move is Ctrl-C on a working install.
run_long() {
    local label="$1"; shift
    local log; log="$(mktemp -t jstack-step)"
    if [ "$DRY_RUN" = "1" ]; then would "$*"; return 0; fi
    "$@" >"$log" 2>&1 &
    local pid=$! start=$SECONDS elapsed
    while kill -0 "$pid" 2>/dev/null; do
        elapsed=$((SECONDS - start))
        printf '\r  %s…%s %s  %ss' "$DIM" "$Z" "$label" "$elapsed"
        sleep 1
    done
    wait "$pid"; local rc=$?
    elapsed=$((SECONDS - start))
    printf '\r\033[2K'
    LAST_LOG="$log"
    LAST_ELAPSED="$elapsed"
    return $rc
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

# ── 0.5 everything this install needs to be told ────────────────────────────
#
# Every question lives here, before any of them is acted on, and there are
# three. Nothing below this block stops to ask.
#
# The rule that decides what belongs here: a question earns its place when the
# answer genuinely differs between machines AND cannot be worked out from the
# machine itself. The root does — a personal Mac, a shared box and an external
# volume are three different right answers. The workspace name does — it is a
# name, and only a person has one. The app does — it downloads a signed
# release from the internet, which is a different kind of decision from
# building a local file.
#
# Everything else got asked once and shouldn't have been. PATH, the host, the
# icon, dateutil, the scheduler: each had exactly one sensible answer, each
# produced a broken-but-green install when answered the other way, and each
# turned a three-minute install into a quiz. They are flags in --help now,
# which is where a rarely-wanted answer belongs.

step "What this install needs to know"

if [ -n "${JSTACK_ROOT:-}" ]; then
    JSTACK_ROOT="${JSTACK_ROOT/#\~/$HOME}"
    case "$JSTACK_ROOT" in
        /*) ok "root declared in the environment — $JSTACK_ROOT" ;;
        *)  die "JSTACK_ROOT=$JSTACK_ROOT is not an absolute path — launchd refuses a relative one and the daemons will not start. Try $HOME/${JSTACK_ROOT#./}" ;;
    esac
else
    # Re-asked until it is absolute, rather than accepted and repaired.
    #
    # A typed "work" used to be taken literally: every derived dir became a
    # relative string, and the plist the scheduler writes put that string in
    # WorkingDirectory and StandardErrorPath — two fields launchd requires to
    # be absolute. The job exited 78 before running a line, KeepAlive retried
    # it forever, and the install ended on a red FAIL naming the daemon rather
    # than the answer that broke it.
    #
    # Silently anchoring it to $HOME would hide the same typo behind a tree
    # nobody meant to create, so the loop says why and shows the fix. Under
    # --yes or with no terminal, ask_value returns the default, which is
    # absolute — so this cannot spin.
    while :; do
        JSTACK_ROOT="$(ask_value "Root for Agents, Logs, Config, State and Credentials" "$HOME")"
        JSTACK_ROOT="${JSTACK_ROOT/#\~/$HOME}"
        case "$JSTACK_ROOT" in
            /*) break ;;
            "") warn "the root cannot be empty" ;;
            *)  warn "a root must be an absolute path — try $HOME/${JSTACK_ROOT#./}" ;;
        esac
        interactive || die "JSTACK_ROOT must be an absolute path"
    done
    if [ "$JSTACK_ROOT" != "$HOME" ]; then
        DECLARE_ROOT=1
        ok "root — $JSTACK_ROOT (declared in your shell profile below)"
    else
        ok "root — $HOME"
    fi
fi
export JSTACK_ROOT

# --agent-root wins where it was given; otherwise the root answer governs.
case "$AGENT_ROOT" in
    "$HOME/Agents") AGENT_ROOT="$JSTACK_ROOT/Agents" ;;
esac

# The second and last question. Asked here rather than at step 4 so both
# answers are given before anything is installed — an install that stops to ask
# something ten minutes in cannot be walked away from.
if [ -z "$AGENT_NAME" ]; then
    AGENT_NAME="$(ask_value "Name for your first agent workspace" "Main")"
fi
ok "first agent — $AGENT_ROOT/$AGENT_NAME"

# ── 1. Claude Code ──────────────────────────────────────────────────────────

step "Claude Code"

CLAUDE="$(command -v claude 2>/dev/null || true)"
[ -n "$CLAUDE" ] || [ ! -x "$HOME/.local/bin/claude" ] || CLAUDE="$HOME/.local/bin/claude"

if [ -n "$CLAUDE" ]; then
    ok "already installed — $("$CLAUDE" --version 2>&1 | head -1)"
elif [ "$WANT_CLAUDE" = "0" ]; then
    warn "not installed, and --no-claude was passed — the plugin cannot be registered without it"
else
    # Not a question: every step after this one registers a plugin, links a
    # rule or installs a command into Claude Code. Answering no here produces
    # an install that finishes green and delivers nothing.
    if [ "$DRY_RUN" = "1" ]; then
        would "curl -fsSL https://claude.ai/install.sh | bash"
    elif run_long "downloading Claude Code" bash -c 'curl -fsSL https://claude.ai/install.sh | bash'; then
        CLAUDE="$HOME/.local/bin/claude"
        ok "installed in ${LAST_ELAPSED}s — $("$CLAUDE" --version 2>&1 | head -1)"
    else
        warn "the Claude Code installer failed; see $LAST_LOG"
    fi
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
    run_long "cloning $REPO_URL" git clone --quiet "$REPO_URL" "$CHECKOUT" || die "clone failed — see $LAST_LOG"
    [ "$DRY_RUN" = "1" ] || ok "cloned in ${LAST_ELAPSED}s at $(git -C "$CHECKOUT" log --oneline -1)"
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
elif [ "$DRY_RUN" = "1" ]; then
    would "append to $PROFILE: $LINE"
else
    # Appended, not asked. Every skill, hook and agent in the stack calls these
    # 18 tools by bare name, so declining left an install that was complete and
    # unusable — and said so in one yellow line above a green verdict. The line
    # is printed instead, which is what a prompt was really for.
    printf '\n%s\n' "$LINE" >> "$PROFILE"
    ok "appended to $PROFILE — open a new shell, or: source $PROFILE"
    note "$LINE"
fi
export PATH="$BIN:$PATH"

# A non-default root is only real if it outlives this shell. Everything the
# stack derives — Agents, Logs, Config, State, Credentials — reads this, so a
# root chosen at install time and never exported is a root that applies to the
# installer and to nothing afterwards.
if [ "$DECLARE_ROOT" = "1" ]; then
    ROOT_LINE="export JSTACK_ROOT=\"$JSTACK_ROOT\""
    if [ -f "$PROFILE" ] && grep -qF "JSTACK_ROOT" "$PROFILE" 2>/dev/null; then
        ok "$PROFILE already declares a root"
    elif [ "$DRY_RUN" = "1" ]; then
        would "append to $PROFILE: $ROOT_LINE"
    else
        printf '%s\n' "$ROOT_LINE" >> "$PROFILE"
        ok "declared JSTACK_ROOT=$JSTACK_ROOT in $PROFILE"
    fi
fi

# ── 7. the scheduler and what it needs ──────────────────────────────────────
#
# Booking and firing are different halves. Without a daemon the registry accepts
# a job, `list` shows it, and the hour passes in silence.
#
# dateutil is installed rather than reported. It is the difference between
# recurring jobs working and not, it is one pip install, and an installer that
# ends by handing the operator a command it could have run itself has not
# finished — that warning was the first thing a fresh install put on screen.

step "Scheduler daemon"

if "$PY" -c 'import dateutil' 2>/dev/null; then
    ok "python-dateutil present"
elif [ "$DRY_RUN" = "1" ]; then
    would "$PY -m pip install --user python-dateutil"
else
    # Two attempts, because the interpreter this resolves to on a Mac with
    # Homebrew is one pip refuses to install into: PEP 668 marks it
    # externally managed and the plain --user install exits 1 with a wall of
    # text about virtualenvs. --break-system-packages is the documented
    # override and Homebrew's own message recommends pairing it with --user,
    # which keeps the package in the user site and out of the managed tree.
    #
    # The verdict is the import, not pip's exit status. A wheel can land and
    # still not be importable by the interpreter the scheduler will run under,
    # and that is the only question worth reporting.
    run_long "installing python-dateutil" "$PY" -m pip install --quiet --user python-dateutil \
        || run_long "installing python-dateutil (PEP 668 override)" \
               "$PY" -m pip install --quiet --user --break-system-packages python-dateutil
    if "$PY" -c 'import dateutil' 2>/dev/null; then
        ok "python-dateutil installed — recurring jobs can book"
    else
        warn "could not install python-dateutil; recurring jobs will not book — see $LAST_LOG"
    fi
fi

# Not a question. `jstack-doctor` runs at the end of this script and grades an
# absent scheduler as a warning — so asking here hands the reader a warning they
# chose and cannot act on. Installed by default; --no-scheduler declines it.
if [ "$WANT_SCHEDULER" = "0" ]; then
    note "skipped by --no-scheduler — run \`jstack-scheduler install\` any time"
elif [ "$DRY_RUN" = "1" ]; then
    would "$BIN/jstack-scheduler install"
else
    "$PY" "$BIN/jstack-scheduler" install && ok "daemon installed" || warn "daemon install reported a problem"
fi

# ── 8. the host and its menu bar icon ───────────────────────────────────────
#
# Steps 1-7 leave a stack you drive from a terminal on this machine. The host
# is what makes the machine reachable at all — from a phone, from another Mac,
# across the tunnel — and the menu bar icon is the only surface that ever says
# whether it is running.
#
# Chained here because the first line of this file promises a working stack in
# one command, and until now it stopped one installer short of one: a stranger
# who ran it got no host and no icon, and nothing on screen said a second
# command existed. That gap was found by installing onto a clean VM and asking
# where the icon was — the answer was that this script never put one there.
#
# The host binds 0.0.0.0 by design (a host only 127.0.0.1 can see is not a
# host) and every route but /api/health requires its bearer token. --no-host
# skips it; `host/install.sh --uninstall` removes it later without touching
# the state or the token.

step "Host and menu bar"

HOST_INSTALLER="$CHECKOUT/host/install.sh"
if [ ! -f "$HOST_INSTALLER" ]; then
    note "no host installer in this checkout — skipped"
elif [ "$WANT_HOST" = "0" ]; then
    note "skipped by --no-host — run $HOST_INSTALLER any time"
else
    # Not a question. The host is the machine's reachability and the icon is
    # the only surface that ever says whether it is running — asking makes
    # both read as extras, and a "no" here produces an install that looks
    # complete and answers nothing. --no-host is the way out, stated in
    # --help, rather than a prompt that has one sensible answer.
    host_args=(--yes)
    [ "$WANT_MENUBAR" = "0" ] && host_args+=(--no-menubar)
    if [ "$DRY_RUN" = "1" ]; then
        would "$HOST_INSTALLER ${host_args[*]}"
    elif bash "$HOST_INSTALLER" "${host_args[@]}"; then
        ok "host installed"
    else
        warn "host install reported a problem — re-run $HOST_INSTALLER to see it"
    fi
fi

# ── 9. the Mac app ──────────────────────────────────────────────────────────
#
# The host makes the machine reachable; the app is what reaches it. Offered
# here rather than left to a second document, for the same reason the host is:
# a machine set up to be reached, with nothing on it that can reach, is half
# an install that reads as a finished one.
#
# It downloads a signed release rather than building from this checkout, which
# is why it is the one step that can be declined without leaving a hole:
# --no-app. app/install.sh verifies the hash, the signature, notarization and
# the signing team before anything lands in /Applications.

step "The Mac app"

APP_INSTALLER="$CHECKOUT/app/install.sh"
if [ "$(uname -s)" != "Darwin" ]; then
    note "macOS only — skipped"
elif [ ! -f "$APP_INSTALLER" ]; then
    note "no app installer in this checkout — skipped"
elif [ "$WANT_APP" = "0" ]; then
    note "skipped by --no-app — run $APP_INSTALLER any time"
elif [ "$DRY_RUN" = "1" ]; then
    would "$APP_INSTALLER"
else
    run_long "downloading and verifying the app" bash "$APP_INSTALLER"
    case $? in
        0) ok "app installed in ${LAST_ELAPSED}s" ;;
        # 3 is "no release published yet" — a fact about the repository that no
        # reader of this output can act on. It gets a note; a warn here would
        # end a clean install on a line that looks like something to fix.
        3) note "no signed release published yet — the app is not part of this install" ;;
        *) warn "app install reported a problem — re-run $APP_INSTALLER to see it: $LAST_LOG" ;;
    esac
fi

# ── 10. the verdict ─────────────────────────────────────────────────────────

step "Verifying"

if [ "$DRY_RUN" = "1" ]; then
    would "$BIN/jstack-doctor"
    printf '\n%sdry run — nothing was changed%s\n' "$B" "$Z"
    exit 0
fi

echo
doctor_out="$(mktemp -t jstack-doctor)"
"$PY" "$BIN/jstack-doctor" | tee "$doctor_out"
rc=${PIPESTATUS[0]}

# The failing checks, by name. The last line used to read "something above is
# broken", which hands the reader a scroll-and-hunt in the one place they most
# need a name — and the doctor already printed every name, so the installer was
# being vaguer than the tool it had just run.
broken="$(awk '$1 == "FAIL" { print $2 }' "$doctor_out" | tr '\n' ' ')"
broken="${broken% }"
rm -f "$doctor_out"

echo
case "$rc" in
    0) printf '%sJStack is installed and every check passed.%s\n' "$GRN$B" "$Z" ;;
    1) printf '%sJStack is installed and working.%s The warnings above are capabilities\nthat stay absent until you add them — normal on a fresh machine.\n' "$GRN$B" "$Z" ;;
    *) printf '%sInstalled, but %s is broken.%s Its FAIL line above names the fix;\nre-run `jstack-doctor` after it.\n' "$YEL$B" "${broken:-a check above}" "$Z" ;;
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
