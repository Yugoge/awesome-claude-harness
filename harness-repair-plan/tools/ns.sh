#!/bin/bash
# Usage: ns.sh <command...>   -- runs command in private mount namespace with sandbox layout
SB="${SB:?set SB to the sandbox root built by sb-setup.sh}"
export SB
exec unshare --mount --propagation private bash -c '
set -e
mount -t tmpfs none /mnt
mkdir -p /mnt/sb /mnt/ccr
mount --bind "$SB" /mnt/sb
[ -d /root/.ccr ] && mount --bind -o ro /root/.ccr /mnt/ccr
mount --bind /mnt/sb/roothome /root
mkdir -p /root/.claude /root/.ccr
mount --bind /mnt/sb/harness /root/.claude
[ -d /mnt/ccr/. ] && [ -n "$(ls -A /mnt/ccr)" ] && mount --bind /mnt/ccr /root/.ccr
mount --bind /mnt/sb/tmp /tmp
mount --bind /mnt/sb/vartmp /var/tmp
mount --bind /mnt/sb/shm /dev/shm
set +e
exec "$@"
' ns "$@"
