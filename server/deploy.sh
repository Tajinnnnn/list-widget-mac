#!/usr/bin/env bash
# Build and deploy to production, then prove what is actually live.
#
# Bare `npx vercel` creates a PREVIEW deployment and does NOT move the
# production alias. That mistake left a sibling project serving 14-day-old
# code while every deploy looked green, so --prod is not optional here and
# the verification step is not optional either.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
"$here/build.sh"

cd "$here"
npx vercel --prod

echo
echo "--- what is actually live ---"
# `alias ls` lists aliases but not which build they resolve to, which is
# exactly how a stale alias hides. inspect names the deployment.
npx vercel inspect "$(npx vercel ls --json 2>/dev/null | head -1)" 2>/dev/null \
  || echo "run: npx vercel inspect <your-domain>   # confirm the commit/age"
