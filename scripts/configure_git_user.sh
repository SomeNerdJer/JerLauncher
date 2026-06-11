#!/bin/sh
# Run once per clone (Mac/Linux/Git Bash) so commits push as SomeNerdJer.
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

# Fix CRLF line endings if these scripts were checked out from Windows.
for f in .githooks/prepare-commit-msg scripts/configure_git_user.sh; do
  if [ -f "$f" ]; then
    sed -i '' $'s/\r$//' "$f" 2>/dev/null || sed -i 's/\r$//' "$f"
  fi
done

git config user.name "SomeNerdJer"
git config user.email "SomeNerdJer@users.noreply.github.com"
git config core.hooksPath .githooks
chmod +x .githooks/prepare-commit-msg 2>/dev/null || true
echo "Git identity set to SomeNerdJer for this repo."
