#!/usr/bin/env bash
# Attach each Privi site's hostname to its Cloudflare Pages project and point DNS at it.
# Only A/AAAA/CNAME records for exactly these hostnames are changed; MX, TXT (email, Google
# Workspace verification) and every other hostname are left alone.
set -euo pipefail
API=https://api.cloudflare.com/client/v4
AUTH=(-H "Authorization: Bearer ${CLOUDFLARE_API_TOKEN}" -H "Content-Type: application/json")
: "${CLOUDFLARE_ACCOUNT_ID:?}" "${ZONE_NAME:?}"

declare -A HOSTS=(
  [home]="www.${ZONE_NAME}" [fortress]="fortress.${ZONE_NAME}" [passport]="passport.${ZONE_NAME}"
  [kya]="kya.${ZONE_NAME}" [mandates]="mandates.${ZONE_NAME}" [gov]="gov.${ZONE_NAME}"
  [chainflow]="chainflow.${ZONE_NAME}" [developers]="developers.${ZONE_NAME}" [live]="live.${ZONE_NAME}"
  [hub]="hub.${ZONE_NAME}" [guard]="guard.${ZONE_NAME}"
)

zone_id=$(curl -fsS "${AUTH[@]}" "$API/zones?name=${ZONE_NAME}" | jq -r '.result[0].id // empty')
[ -n "$zone_id" ] || { echo "::error::zone ${ZONE_NAME} not found for this token"; exit 1; }

fail=0
for site in "${!HOSTS[@]}"; do
  host="${HOSTS[$site]}"; project="privi-${site}"; target="${project}.pages.dev"
  case "$host" in "${ZONE_NAME}"|"explorer.${ZONE_NAME}") echo "::error::refusing to touch ${host}"; exit 1;; esac
  echo "== ${host} -> ${target}"

  # 1. custom domain on the Pages project (409/already exists is fine)
  out=$(curl -sS "${AUTH[@]}" -X POST "$API/accounts/${CLOUDFLARE_ACCOUNT_ID}/pages/projects/${project}/domains" \
        --data "{\"name\":\"${host}\"}")
  if [ "$(echo "$out" | jq -r .success)" != "true" ] && ! echo "$out" | grep -qi "already"; then
    echo "::warning::${host}: could not add to ${project}: $(echo "$out" | jq -c .errors)"; fail=1
  fi

  # 2. DNS: replace A/AAAA for this exact name, upsert a proxied CNAME to the Pages project
  recs=$(curl -fsS "${AUTH[@]}" "$API/zones/${zone_id}/dns_records?name=${host}&per_page=100")
  for id in $(echo "$recs" | jq -r '.result[] | select(.type=="A" or .type=="AAAA") | .id'); do
    curl -fsS "${AUTH[@]}" -X DELETE "$API/zones/${zone_id}/dns_records/${id}" >/dev/null && echo "   removed old A/AAAA record"
  done
  cname=$(echo "$recs" | jq -r '.result[] | select(.type=="CNAME") | .id' | head -n1)
  body="{\"type\":\"CNAME\",\"name\":\"${host}\",\"content\":\"${target}\",\"proxied\":true,\"ttl\":1,\"comment\":\"Privi site on Cloudflare Pages\"}"
  if [ -n "$cname" ]; then
    curl -fsS "${AUTH[@]}" -X PUT "$API/zones/${zone_id}/dns_records/${cname}" --data "$body" >/dev/null && echo "   CNAME updated"
  else
    curl -fsS "${AUTH[@]}" -X POST "$API/zones/${zone_id}/dns_records" --data "$body" >/dev/null && echo "   CNAME created"
  fi
done

exit $fail
