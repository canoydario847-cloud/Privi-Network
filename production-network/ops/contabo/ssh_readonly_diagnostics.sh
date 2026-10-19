#!/usr/bin/env bash
# Read-only SSH diagnosis for an owner-controlled valueless Privi staging host.
# Run INSIDE the authorized VPS console. No network requests, no writes,
# no passwords or private keys accessed. Does not activate the PRVI mainnet.
set -u
export LC_ALL=C

printf 'Privi Contabo SSH diagnostic — READ ONLY\n'

active=no
for unit in ssh.service ssh.socket sshd.service; do
  if command -v systemctl >/dev/null 2>&1 && systemctl is-active --quiet "$unit" 2>/dev/null; then
    printf 'ACTIVE: %s\n' "$unit"
    active=yes
  fi
done
if [[ "$active" != yes ]]; then
  printf 'WARN: Neither ssh.service, ssh.socket nor sshd.service is active\n'
fi

if ! command -v ss >/dev/null 2>&1; then
  printf 'WARN: Cannot inspect TCP listeners (ss command unavailable)\n'
  exit 3
fi

# Return only port-22 bind information, never other processes or sockets.
listeners=$(ss -lntH 2>/dev/null | awk '
{
    localaddr=$4
    if (localaddr ~ /:22$/) print localaddr
}' || true)

if [[ -z "$listeners" ]]; then
  printf 'FAIL: No TCP listener on port 22\n'
  printf 'Check OpenSSH service/socket, sshd configuration and journalctl using VNC.\n'
  exit 2
fi

publicbind=no
while IFS= read -r address; do
  [[ -n "$address" ]] || continue
  case "$address" in
    127.*:22|\[::1\]:22|::1:22)
      printf 'LOCAL ONLY: SSH listener is bound to loopback\n'
      ;;
    *:22)
      printf 'LISTENING: SSH has a non-loopback bind on TCP/22\n'
      publicbind=yes
      ;;
  esac
done <<< "$listeners"

if command -v ufw >/dev/null 2>&1; then
  state=$(ufw status 2>/dev/null | head -n 1 || true)
  if [[ "$state" == "Status: active" ]]; then
    printf 'INFO: UFW active; review SSH allow rules without disabling firewall\n'
  elif [[ "$state" == "Status: inactive" ]]; then
    printf 'INFO: UFW inactive; provider/network firewall may still apply\n'
  else
    printf 'WARN: UFW state unavailable (root may be required)\n'
  fi
else
  printf 'INFO: UFW unavailable; check installed firewall stack\n'
fi

if [[ "$publicbind" == no ]]; then
  printf 'FAIL: SSH only listens on loopback; remote connections cannot reach TCP/22\n'
  exit 2
fi

printf 'PASS: SSH has a non-loopback listener. External reachability is NOT proven.\n'
printf 'If external connections are refused, check Contabo firewall and host ACLs via the customer panel and trusted VNC console.\n'
printf 'No firewall rules, SSH settings, or credentials were changed.\n'
