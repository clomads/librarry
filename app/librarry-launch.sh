#!/usr/bin/env bash
# Launcher for Librarry (app grid entry). "stop" stops the containers.
DIR="$(cd "$(dirname "$0")" && pwd)"
if [[ "${1:-}" == stop ]]; then exec "$DIR/../stack/stackctl.sh" down; fi
# Opening Librarry replaces a running copy, so a fresh launch always loads the latest app code.
# (Test snapshots run alongside with their own profile and leave the real window alone.)
if [[ -z "${LIBRARY_SNAPSHOT:-}" ]]; then
  for pid in $(pgrep -f "^$DIR/node_modules/electron/dist/electron .*--ozone-platform-hint"); do
    [[ "$(tr '\0' '\n' < /proc/$pid/environ 2>/dev/null | grep -c '^LIBRARY_SNAPSHOT=')" == 0 ]] && kill "$pid"
  done
  for _ in {1..20}; do pgrep -f "^$DIR/node_modules/electron/dist/electron .*--ozone-platform-hint" >/dev/null || break; sleep 0.25; done
fi
cd "$DIR" && exec ./node_modules/.bin/electron --ozone-platform-hint=auto --enable-wayland-ime . "$@"
