#!/usr/bin/env bash
# sync-method.sh — safely propagate the GLOBAL method scaffold into a target repo.
#
# Source layout must be canonical:
#   docs/method/METHOD.md
#   docs/method/README.md
#   docs/method/PROJECT.md        (template only; target PROJECT.md preserved)
#   docs/method/sync-method.sh
#   docs/specs/README.md          (created if missing in target)
#   docs/specs/TEMPLATE-track-f.md
#   docs/specs/TEMPLATE-track-l.md
#   docs/decisions/README.md      (created if missing in target)
#   docs/decisions/TEMPLATE-decision.md (created if missing in target)
#   docs/status/README.md         (created if missing in target)
#   docs/verification/README.md   (created if missing in target)
#
# Usage:
#   ./docs/method/sync-method.sh /path/to/target-repo

set -euo pipefail

LOAD_LINE='Before starting any task, load docs/method/METHOD.md then docs/method/PROJECT.md and treat both as binding.'
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC_ROOT="$(cd "$SRC/../.." && pwd)"
TARGET="${1:?usage: ./sync-method.sh /path/to/target-repo}"

if [[ ! -d "$TARGET" ]]; then
  echo "error: target '$TARGET' is not a directory" >&2
  exit 1
fi

required=(
  "$SRC/METHOD.md"
  "$SRC/README.md"
  "$SRC/PROJECT.md"
  "$SRC/sync-method.sh"
  "$SRC_ROOT/docs/specs/README.md"
  "$SRC_ROOT/docs/specs/TEMPLATE-track-f.md"
  "$SRC_ROOT/docs/specs/TEMPLATE-track-l.md"
  "$SRC_ROOT/docs/decisions/README.md"
  "$SRC_ROOT/docs/decisions/TEMPLATE-decision.md"
  "$SRC_ROOT/docs/status/README.md"
  "$SRC_ROOT/docs/verification/README.md"
)

missing=0
for f in "${required[@]}"; do
  if [[ ! -f "$f" ]]; then
    echo "error: required source missing: $f" >&2
    missing=1
  fi
done
if [[ "$missing" -ne 0 ]]; then
  echo "refusing to write partial scaffold" >&2
  exit 2
fi

mkdir -p "$TARGET/docs/method" "$TARGET/docs/specs" "$TARGET/docs/decisions" "$TARGET/docs/status" "$TARGET/docs/verification"

copy_atomic() {
  local src="$1" dest="$2" mode="${3:-644}" tmp
  mkdir -p "$(dirname "$dest")"
  tmp="$(mktemp "${dest}.tmp.XXXXXX")"
  cp "$src" "$tmp"
  chmod "$mode" "$tmp"
  mv "$tmp" "$dest"
}

copy_if_missing() {
  local src="$1" dest="$2" mode="${3:-644}"
  if [[ -f "$dest" ]]; then
    echo "kept existing ${dest#$TARGET/}"
  else
    copy_atomic "$src" "$dest" "$mode"
    echo "created ${dest#$TARGET/}"
  fi
}

# Global files — overwritten after all source checks pass.
copy_atomic "$SRC/METHOD.md" "$TARGET/docs/method/METHOD.md" 644
copy_atomic "$SRC/README.md" "$TARGET/docs/method/README.md" 644
copy_atomic "$SRC/sync-method.sh" "$TARGET/docs/method/sync-method.sh" 755
copy_atomic "$SRC_ROOT/docs/specs/TEMPLATE-track-f.md" "$TARGET/docs/specs/TEMPLATE-track-f.md" 644
copy_atomic "$SRC_ROOT/docs/specs/TEMPLATE-track-l.md" "$TARGET/docs/specs/TEMPLATE-track-l.md" 644

# Directory discipline files — create if missing, preserve local edits.
copy_if_missing "$SRC_ROOT/docs/specs/README.md" "$TARGET/docs/specs/README.md" 644
copy_if_missing "$SRC_ROOT/docs/decisions/README.md" "$TARGET/docs/decisions/README.md" 644
copy_if_missing "$SRC_ROOT/docs/decisions/TEMPLATE-decision.md" "$TARGET/docs/decisions/TEMPLATE-decision.md" 644
copy_if_missing "$SRC_ROOT/docs/status/README.md" "$TARGET/docs/status/README.md" 644
copy_if_missing "$SRC_ROOT/docs/verification/README.md" "$TARGET/docs/verification/README.md" 644

# Local files — create only if missing.
if [[ ! -f "$TARGET/docs/method/PROJECT.md" ]]; then
  copy_atomic "$SRC/PROJECT.md" "$TARGET/docs/method/PROJECT.md" 644
  echo "created PROJECT.md from template — edit it for this repo before first use"
else
  echo "kept existing PROJECT.md (local customization preserved)"
fi

if [[ ! -f "$TARGET/docs/method/DESIGN-RECORD.md" ]]; then
  cat > "$TARGET/docs/method/DESIGN-RECORD.md" <<'EOF'
# Design Record

No prior method history detected; method scaffold installed by sync-method.sh.
EOF
  echo "created DESIGN-RECORD.md"
else
  echo "kept existing DESIGN-RECORD.md"
fi

# Add the AGENTS.md hook exactly once. If duplicates exist, collapse them.
AGENTS="$TARGET/AGENTS.md"
if [[ -f "$AGENTS" ]]; then
  tmp="$(mktemp "${AGENTS}.tmp.XXXXXX")"
  awk -v line="$LOAD_LINE" 'BEGIN{seen=0} { if ($0 == line) { if (!seen) { print; seen=1 } } else { print } } END{ if (!seen) print line }' "$AGENTS" > "$tmp"
  mv "$tmp" "$AGENTS"
else
  printf '%s\n' "$LOAD_LINE" > "$AGENTS"
fi

echo "synced method scaffold into $TARGET"
