#!/bin/sh
# Prepare Railway volume and drop root permissions before starting evmd.
set -eu
if [ "$(id -u)" -ne 0 ]; then
  echo "Requires root only to prepare /data before dropping privileges" >&2
  exit 1
fi
mkdir -p /data
chown 1025:1025 /data
chmod 0700 /data
exec su-exec nonroot /usr/local/bin/start-node.sh
