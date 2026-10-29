#!/usr/bin/env bash
# Host-side control for the library stack (used by the library app).
#   stackctl.sh up | down | status | check | update <service|all> | recreate-vpn | vpn <vpnctl args>
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
SERVICES=(gluetun transmission flood prowlarr sonarr radarr lidarr whisparr jellyfin seerr)
VPN_SHARED=(transmission flood prowlarr sonarr radarr lidarr whisparr)

compose() {
  distrobox enter deb12 -- env DOCKER_HOST=unix:///run/user/1000/podman/podman.sock \
    docker compose -f "$DIR/compose.yml" --project-directory "$DIR" "$@"
}

image_of() { podman inspect -f '{{.ImageName}}' "$1" 2>/dev/null; }

status() {
  local first=1
  printf '['
  for s in "${SERVICES[@]}"; do
    local img state run_id cur_id upd=false
    img=$(image_of "$s" || true)
    state=$(podman inspect -f '{{.State.Status}}' "$s" 2>/dev/null || echo missing)
    run_id=$(podman inspect -f '{{.Image}}' "$s" 2>/dev/null || true)
    cur_id=$(podman image inspect -f '{{.Id}}' "$img" 2>/dev/null || true)
    [[ -n "$run_id" && -n "$cur_id" && "$run_id" != "$cur_id" ]] && upd=true
    created=$(podman image inspect -f '{{.Created.Format "2006-01-02"}}' "$run_id" 2>/dev/null || true)
    [[ $first == 1 ]] || printf ','; first=0
    printf '{"name":"%s","state":"%s","image":"%s","built":"%s","update":%s}' "$s" "$state" "$img" "$created" "$upd"
  done
  printf ']\n'
}

recreate_vpn() {
  # podman won't replace gluetun while apps share its network namespace:
  # remove them, recreate gluetun, then bring them back on the new namespace
  compose rm -sf "${VPN_SHARED[@]}"
  compose up -d --force-recreate gluetun
  compose up -d "${VPN_SHARED[@]}"
}

mount_ha() {
  # HA media/meds (the offload library): CIFS automount at /mnt/ha-media (mount-ha-media.sh);
  # touching it triggers the mount before containers bind it
  timeout 60 ls /mnt/ha-media/meds >/dev/null 2>&1 || echo "warning: HA media share not reachable" >&2
}

case "${1:-status}" in
  up) mount_ha; compose up -d --remove-orphans ;;
  recreate-vpn) recreate_vpn ;;
  vpn) shift; exec "$DIR/vpnctl.py" "$@" ;;
  down) compose down ;;
  status) status ;;
  check)  # pull newer images without touching running containers
    for s in "${SERVICES[@]}"; do img=$(image_of "$s") && podman pull -q "$img" >/dev/null || true; done
    status ;;
  update)
    target="${2:?service or all}"
    if [[ "$target" == all ]]; then
      compose pull && compose up -d
    else
      podman pull -q "$(image_of "$target")" >/dev/null
      if [[ "$target" == gluetun ]]; then
        recreate_vpn
      else
        compose up -d "$target"
      fi
    fi
    status ;;
  *) echo "usage: $0 up|down|status|check|update <service|all>" >&2; exit 2 ;;
esac
