#!/usr/bin/env bash
# VPS hardening for Neo-Label — run on the production server as root.
#
# What this does (three independent layers):
#   1. unattended-upgrades  — auto-apply Ubuntu security patches nightly
#   2. UFW                  — firewall: only 22/80/443 in, everything else blocked
#   3. fail2ban             — ban IPs that brute-force SSH (5 fails in 10min → 1h ban)
#
# What this does NOT touch: sshd_config. SSH continues to work exactly
# as it does today (root login + password auth both stay enabled). The
# only change SSH will "feel" is that failed login attempts from hostile
# IPs get dropped by fail2ban before reaching sshd.
#
# Idempotent — safe to re-run. UFW rules are reset and reapplied each time.
#
# Usage (on the VPS, as root):
#   cd /root/work/neo-label && git pull && bash harden.sh

set -euo pipefail

if [[ "$EUID" -ne 0 ]]; then
    echo "ERROR: harden.sh must run as root." >&2
    exit 1
fi

step() { printf '\n==> %s\n' "$*"; }
sub()  { printf '    %s\n' "$*"; }

# Pre-flight — confirm SSH is on port 22, otherwise UFW rule below is wrong.
SSH_PORT="$(sshd -T 2>/dev/null | awk '/^port /{print $2; exit}')"
if [[ -z "${SSH_PORT:-}" ]]; then SSH_PORT=22; fi
if [[ "$SSH_PORT" != "22" ]]; then
    echo "WARNING: sshd is listening on port $SSH_PORT, not 22." >&2
    echo "Edit harden.sh to open that port in UFW, or abort now." >&2
    read -r -p "Continue with port 22 anyway? [y/N] " ans
    [[ "$ans" == "y" || "$ans" == "Y" ]] || exit 1
fi

# ---------- 1. unattended-upgrades ----------
step "unattended-upgrades"
apt-get update -qq
DEBIAN_FRONTEND=noninteractive apt-get install -y -qq unattended-upgrades >/dev/null
cat >/etc/apt/apt.conf.d/20auto-upgrades <<'EOF'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
EOF
sub "wrote /etc/apt/apt.conf.d/20auto-upgrades"
systemctl enable --now apt-daily.timer apt-daily-upgrade.timer >/dev/null 2>&1 || true
sub "apt timers enabled"
systemctl list-timers apt-daily*.timer --no-pager 2>/dev/null \
    | awk 'NR==1 || /apt-daily/' | sed 's/^/    /'

# ---------- 2. UFW ----------
step "UFW firewall"
DEBIAN_FRONTEND=noninteractive apt-get install -y -qq ufw >/dev/null

# Reset then reapply — guarantees a clean, declarative state every run.
ufw --force reset >/dev/null
ufw default deny incoming  >/dev/null
ufw default allow outgoing >/dev/null
ufw allow 22/tcp  comment 'SSH'   >/dev/null
ufw allow 80/tcp  comment 'HTTP'  >/dev/null
ufw allow 443/tcp comment 'HTTPS' >/dev/null
ufw --force enable >/dev/null
ufw status verbose | sed 's/^/    /'

# ---------- 3. fail2ban ----------
step "fail2ban"
DEBIAN_FRONTEND=noninteractive apt-get install -y -qq fail2ban >/dev/null
cat >/etc/fail2ban/jail.local <<'EOF'
[DEFAULT]
bantime  = 1h
findtime = 10m
maxretry = 5
backend  = systemd

[sshd]
enabled = true
port    = 22
EOF
sub "wrote /etc/fail2ban/jail.local"
systemctl enable fail2ban >/dev/null
systemctl restart fail2ban
sleep 1
fail2ban-client status sshd 2>&1 | sed 's/^/    /' || true

# ---------- summary ----------
step "done"
sub "unattended-upgrades: $(systemctl is-enabled apt-daily-upgrade.timer 2>/dev/null || echo '?')"
sub "ufw:                 $(ufw status | head -1 | awk '{print $2}')"
sub "fail2ban:            $(systemctl is-active fail2ban)"
echo
echo "    SSH sessions are NOT affected. Open a new session to verify."
