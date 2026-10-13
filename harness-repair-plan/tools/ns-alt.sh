#!/bin/bash
SB="${SB:?set SB to the sandbox root built by sb-setup.sh}"
export SB
exec unshare --mount --propagation private bash -c '
set -e
mount -t tmpfs none /mnt
mkdir -p /mnt/sb; mount --bind "$SB" /mnt/sb
mount -t tmpfs none /root
mount -t tmpfs none /home
mkdir -p /home/alice
mount --bind /mnt/sb/alt/home /home/alice
mkdir -p /home/alice/.claude
mount --bind /mnt/sb/harness-boot /home/alice/.claude
mount --bind /mnt/sb/alt/tmp /tmp
mount --bind /mnt/sb/alt/vartmp /var/tmp
mount --bind /mnt/sb/alt/shm /dev/shm
set +e
export RV_HOME=/home/alice RV_CLAUDE=/home/alice/.claude
exec "$@"
' ns "$@"
