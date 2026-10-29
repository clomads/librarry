#!/usr/bin/env bash
# One-time root setup: mount HA's "media" Samba share at /mnt/ha-media with a real
# kernel CIFS mount (gvfs can't delete or rename files, which the arrs need).
# Run on the host with:  sudo ~/claudecode/librarry/stack/migrate/mount-ha-media.sh
# (from the deb12 box:   host-spawn sudo ~/claudecode/librarry/stack/migrate/mount-ha-media.sh)
set -euo pipefail
[[ -e /run/.containerenv ]] && { echo "run this on the host, not in the deb12 box: host-spawn sudo $0"; exit 1; }
[[ $EUID -eq 0 ]] || { echo "run with sudo"; exit 1; }
CRED=/etc/samba/ha-media.cred
if [[ ! -s $CRED ]]; then
  read -rp "Home Assistant Samba username: " u
  read -rsp "Home Assistant Samba password: " p; echo
  install -d -m 755 /etc/samba
  umask 077; printf 'username=%s\npassword=%s\n' "$u" "$p" > "$CRED"
fi
install -d /mnt/ha-media
LINE="//homeassistant.local/media /mnt/ha-media cifs credentials=$CRED,uid=1000,gid=1000,file_mode=0664,dir_mode=0775,context=system_u:object_r:container_file_t:s0,_netdev,nofail,x-systemd.automount,x-systemd.mount-timeout=30 0 0"
grep -q ' /mnt/ha-media ' /etc/fstab || echo "$LINE" >> /etc/fstab
systemctl daemon-reload
systemctl restart remote-fs.target
ls /mnt/ha-media/meds >/dev/null && echo "mounted: $(ls /mnt/ha-media/meds | tr '\n' ' ')"
