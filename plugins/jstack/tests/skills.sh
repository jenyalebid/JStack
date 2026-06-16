#!/usr/bin/env bash
# JStack live test — skills manifest validation.
#
# Validates every skill bundled under plugins/jstack/skills/ as a live artifact:
#   - SKILL.md exists and is non-empty
#   - YAML frontmatter present, well-formed, with name + description
#   - frontmatter `name:` matches the directory name (skill ID must be stable)
#   - any bin/* adapters the skill references actually exist + are executable
#
# Validation is per-skill so failures localize. Each systems.json skill entry
# points at this same script — running it produces a full report. Exit 0 = all
# pass, exit 1 = any fail.
#
# Live, in the sense that matters: parses the real shipped SKILL.md, checks
# the real bin/ adapters on disk. Catches the most common drift (rename, delete,
# broken path) without spinning up a Claude session.

set -u

PLUGIN_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SKILLS_DIR="$PLUGIN_ROOT/skills"
BIN_DIR="$PLUGIN_ROOT/bin"

if [[ ! -d "$SKILLS_DIR" ]]; then
  echo "FAIL: skills dir missing at $SKILLS_DIR" >&2
  exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "FAIL: python3 not on PATH" >&2
  exit 1
fi

fails=0

validate_frontmatter() {
  local skill_md="$1"
  python3 - "$skill_md" <<'PY'
import re, sys
from pathlib import Path
p = Path(sys.argv[1])
text = p.read_text()
if not text.startswith("---"):
    print(f"no frontmatter: {p}")
    sys.exit(1)
end = text.find("\n---", 3)
if end == -1:
    print(f"unterminated frontmatter: {p}")
    sys.exit(1)
block = text[3:end]
fields = {}
for line in block.splitlines():
    m = re.match(r'^([a-zA-Z_][a-zA-Z0-9_-]*)\s*:\s*(.*)$', line)
    if m:
        fields[m.group(1)] = m.group(2).strip().strip('"').strip("'")
expected_name = p.parent.name
got_name = fields.get("name", "")
got_desc = fields.get("description", "")
if got_name != expected_name:
    print(f"name mismatch: dir={expected_name} frontmatter={got_name}")
    sys.exit(1)
if not got_desc:
    print(f"empty description: {p}")
    sys.exit(1)
PY
}

check_bin_refs() {
  local skill_md="$1"
  shift
  local missing=()
  for adapter in "$@"; do
    if [[ ! -x "$BIN_DIR/$adapter" ]]; then
      missing+=("$adapter")
    fi
  done
  if [[ ${#missing[@]} -gt 0 ]]; then
    echo "missing bin adapter(s): ${missing[*]}"
    return 1
  fi
  return 0
}

run_skill() {
  local name="$1"
  shift
  local skill_md="$SKILLS_DIR/$name/SKILL.md"

  if [[ ! -f "$skill_md" ]]; then
    echo "FAIL [$name]: SKILL.md missing at $skill_md" >&2
    fails=$((fails+1))
    return
  fi
  if [[ ! -s "$skill_md" ]]; then
    echo "FAIL [$name]: SKILL.md empty" >&2
    fails=$((fails+1))
    return
  fi

  if ! err=$(validate_frontmatter "$skill_md" 2>&1); then
    echo "FAIL [$name]: $err" >&2
    fails=$((fails+1))
    return
  fi

  if [[ $# -gt 0 ]]; then
    if ! err=$(check_bin_refs "$skill_md" "$@" 2>&1); then
      echo "FAIL [$name]: $err" >&2
      fails=$((fails+1))
      return
    fi
  fi

  echo "PASS [$name]"
}

# Skill → required bin adapters (referenced in its SKILL.md procedure)
run_skill install-rules
run_skill handoff open-terminal-here
run_skill audit open-terminal-here
run_skill save file-followup
run_skill active
run_skill push
run_skill post-session-review file-followup log_event
run_skill showme open-artifact

# Catch skills added to skills/ but not registered above
for dir in "$SKILLS_DIR"/*/; do
  name=$(basename "$dir")
  if ! grep -qE "^run_skill $name( |$)" "$0"; then
    echo "FAIL [$name]: skill present in skills/ but not registered in tests/skills.sh" >&2
    fails=$((fails+1))
  fi
done

echo ""
if [[ $fails -gt 0 ]]; then
  echo "$fails skill(s) failed validation" >&2
  exit 1
fi
echo "ALL PASS — 8 skills verified"
