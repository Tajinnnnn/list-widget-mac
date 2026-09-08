#!/usr/bin/env bash
# Assemble the deployable tree from the parent project.
#
# Everything this script writes is a COPY and is gitignored. The sources
# live one directory up. That is deliberate: vendoring these into git is
# how the server's merge and the Mac app's merge would silently drift
# apart, which is the specific failure the design set out to avoid.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
root="$(cd "$here/.." && pwd)"

for module in vault_sync.py sync_api.py sync_store.py; do
  cp "$root/$module" "$here/$module"
done

mkdir -p "$here/public"
cp "$root/todo.html" "$here/public/index.html"

# PWA icons, rendered from the app icon that make_icon.py already produces
# so there is one source of truth for the artwork. sips is built into macOS.
if [[ -f "$root/icon.icns" ]]; then
  for size in 192 512; do
    sips -s format png --resampleHeightWidth "$size" "$size" \
      "$root/icon.icns" --out "$here/public/icon-${size}.png" >/dev/null
  done
else
  echo "warning: icon.icns missing — run 'uv run python make_icon.py' first" >&2
fi

echo "build ok:"
ls -1 "$here"/*.py "$here"/public
