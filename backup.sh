#!/usr/bin/env bash
# Back up NeoLabel runtime data + secrets to a directory outside the
# project tree, so the data survives a bad deploy, accidental rm, or
# repo reset. Not an offsite backup — protects against project-local
# problems only. For disaster recovery of the whole VPS, pull these
# archives to another host.
#
# What goes in the tarball:
#   - /root/work/neo-label-data/       (all items, frames, videos, annotations, users.json)
#   - /root/work/neo-label/seed_users.json
#   - /root/work/neo-label/.env.prod
#
# Install as nightly cron (run as root on the VPS):
#   ( crontab -l 2>/dev/null; echo "0 3 * * * /root/work/neo-label/backup.sh >> /var/log/neo-label-backup.log 2>&1" ) | crontab -
#
# Restore:
#   mkdir /tmp/restore && tar -xzf /root/neo-label-backups/neo-label-YYYYMMDD-HHMMSS.tar.gz -C /tmp/restore
#   # inspect, then copy back into place and fix ownership:
#   cp -a /tmp/restore/root/work/neo-label-data /root/work/
#   chown -R 1000:1000 /root/work/neo-label-data

set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-/root/neo-label-backups}"
DATA_DIR="${DATA_DIR:-/root/work/neo-label-data}"
REPO_DIR="${REPO_DIR:-/root/work/neo-label}"
RETENTION_COUNT="${RETENTION_COUNT:-5}"

for path in "$DATA_DIR" "$REPO_DIR/seed_users.json" "$REPO_DIR/.env.prod"; do
  [[ -e "$path" ]] || { echo "missing: $path" >&2; exit 1; }
done

mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"

ts="$(date +%Y%m%d-%H%M%S)"
out="$BACKUP_DIR/neo-label-$ts.tar.gz"

tar -czf "$out" \
  "$DATA_DIR" \
  "$REPO_DIR/seed_users.json" \
  "$REPO_DIR/.env.prod"

chmod 600 "$out"

# Keep only the newest $RETENTION_COUNT archives. Sort by mtime descending,
# skip the first N, delete the rest. Runs only after the tar above succeeded
# (set -e), so a broken script never wipes the last known-good backup.
find "$BACKUP_DIR" -maxdepth 1 -name 'neo-label-*.tar.gz' -type f -printf '%T@ %p\n' \
  | sort -rn \
  | awk -v n="$RETENTION_COUNT" 'NR>n {print $2}' \
  | xargs -r rm -f

size="$(du -h "$out" | cut -f1)"
echo "[$(date -Iseconds)] backup ok: $out ($size)"
