#!/bin/sh
# Run once per clone (Mac/Linux/Git Bash) so commits push as SomeNerdJer.
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
git config user.name "SomeNerdJer"
git config user.email "SomeNerdJer@users.noreply.github.com"
git config core.hooksPath .githooks
chmod +x .githooks/prepare-commit-msg 2>/dev/null || true
echo "Git identity set to SomeNerdJer for this repo."
