#!/bin/bash
# Run a command up to N times and stop at the first success:  scripts/retry.sh 3 <command> [args...]
#
# Used for the time-sensitive checks in CI and release (native export, PDF probe, Mermaid page): on GitHub's
# shared, display-less runners one attempt now and then runs slow and times out, although the same check
# passes in seconds on a normal Mac. A real regression fails every attempt, so it still fails the run.
# A pass that needed more than one attempt is printed as a warning so flakiness stays visible.
set -u
attempts="$1"; shift
for ((n = 1; n <= attempts; n++)); do
  if "$@"; then
    [ "$n" -gt 1 ] && echo "::warning::passed only on attempt $n of $attempts: $*"
    exit 0
  fi
  echo "::warning::attempt $n of $attempts failed: $*"
done
echo "::error::failed on all $attempts attempts: $*"
exit 1
