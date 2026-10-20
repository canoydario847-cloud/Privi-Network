#!/usr/bin/env bash
# Read-only security/sizing check for ONE Ubuntu 24.04 staging VPS.
# VALELESS staging only. Never starts blockchain or makes network requests.
set -u
export LC_ALL=C
fails=0
warnings=0
pass() { printf 'PASS: %s\n' "$1"; }
warn() { printf 'WARN: %s\n' "$1"; warnings=$((warnings+1)); }
fail() { printf 'FAIL: %s\n' "$1"; fails=$((fails+1)); }

printf 'PRIVI VALELESS STAGING — READ-ONLY HOST PROBE\n'

# For the newly ordered 8-vCPU staging VPS, set PRIVI_EXPECTED_VCPU=8.
# Default remains six for the earlier Cloud VPS 6 and existing CI fixtures.
# This is configuration observation only and never contacts a provider API.
expected_vcpu="${PRIVI_EXPECTED_VCPU:-6}"
if [[ ! "$expected_vcpu" =~ ^[1-9][0-9]?$|^1[01][0-9]$|^12[0-8]$ ]]; then
  fail 'Expected vCPU threshold must be an integer from 1 to 128'
  exit 2
fi
if [[ -r /etc/os-release ]]; then
  . /etc/os-release
  if [[ "${ID:-}" == ubuntu && "${VERSION_ID:-}" == 24.04 ]]; then
    pass 'Expected Ubuntu 24.04 base image'
  else
    fail 'OS is not verified Ubuntu 24.04'
  fi
else
  fail 'Cannot verify operating-system image'
fi

if [[ "$(uname -m)" == x86_64 ]]; then
  pass 'x86_64 architecture'
else
  warn 'Non-x86_64 architecture; verify Cosmos EVM binary compatibility'
fi

# Count available CPUs relative to the verified subscription (6 or 8).
# Hypervisor capacity and isolation cannot be inferred from nproc alone.
if command -v nproc >/dev/null 2>&1; then
  cpus=$(nproc)
  if [[ "$cpus" =~ ^[0-9]+$ ]] && (( cpus >= expected_vcpu )); then
    pass "At least ${expected_vcpu} available vCPU"
  else
    fail "Fewer than ${expected_vcpu} available vCPU; verify Contabo plan, provisioning and CPU affinity"
  fi
else
  fail 'Cannot confirm available vCPU count'
fi

if [[ -r /proc/meminfo ]]; then
  kb=$(awk '/^MemTotal:/ {print $2; exit}' /proc/meminfo)
  if [[ "$kb" =~ ^[0-9]+$ ]] && (( kb >= 10 * 1024 * 1024 )); then
    pass 'At least 10 GiB reported RAM (Cloud VPS 6 staging floor)'
  else
    fail 'Fewer than 10 GiB RAM or unreadable memory report'
  fi
else
  fail 'Cannot verify memory'
fi

if command -v df >/dev/null 2>&1; then
  free_kb=$(df -Pk / | awk 'NR==2 {print $4}')
  if [[ "$free_kb" =~ ^[0-9]+$ ]] && (( free_kb >= 60 * 1024 * 1024 )); then
    pass 'At least 60 GiB free on root filesystem for staging'
  else
    fail 'Fewer than 60 GiB free on root filesystem for staging'
  fi
else
  fail 'Cannot inspect root filesystem'
fi

if command -v timedatectl >/dev/null 2>&1; then
  synchronized=$(timedatectl show -p NTPSynchronized --value 2>/dev/null || true)
  if [[ "$synchronized" == yes ]]; then
    pass 'NTP clock synchronized'
  else
    warn 'Clock synchronization unverified'
  fi
else
  warn 'Clock synchronization tool not installed'
fi

if command -v ss >/dev/null 2>&1; then
  sockets=$(ss -lntH 2>/dev/null || true)
  if [[ -z "$sockets" ]]; then
    warn 'Cannot verify TCP listeners'
  else
    exposed=$(awk '
      {
        addr=$4
        gsub(/\[|\]/, "", addr)
        count=split(addr, parts, ":")
        port=parts[count]
        if (port !~ /^(8545|8546|26657|26660|1317|9090|9091)$/) next
        if (addr ~ /^127\./ || addr ~ /^::1:/) next
        print port
      }
    ' <<< "$sockets" | sort -u | paste -sd ',' -)
    if [[ -n "$exposed" ]]; then
      fail 'RPC/metrics listener bound to non-loopback address'
    else
      pass 'Common RPC/metrics ports are not exposed by local listeners'
    fi
  fi
else
  warn 'ss unavailable; listener check skipped'
fi

if command -v ufw >/dev/null 2>&1; then
  state=$(ufw status 2>/dev/null | head -n 1 || true)
  if [[ "$state" == 'Status: active' ]]; then
    pass 'Host firewall active (rules need separate review)'
  else
    warn 'UFW inactive/unreadable; verify recovery before enabling firewall'
  fi
else
  warn 'UFW unavailable'
fi

printf 'SUMMARY: %d hard failures; %d warnings\n' "$fails" "$warnings"
printf 'No cloud credentials, no cloud provisioning and no financial mainnet.\n'
if (( fails > 0 )); then
  exit 2
fi
exit 0
