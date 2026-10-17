# Privi seven-validator Railway staging image — valueless TEST only.
# Build from the repository root with dockerfilePath production-network/seven-validator/railway/Dockerfile.
FROM golang:1.25.9-alpine AS builder
RUN apk add --no-cache curl build-base git bash file linux-headers eudev-dev
WORKDIR /src
RUN git clone --depth 1 --branch v0.7.3 https://github.com/cosmos/evm.git . \
 && test "$(git rev-parse HEAD)" = "c3ae9067a7eadcdea55a5192226916deb44c71c4" \
 && grep -Fxq 'go 1.25.9' go.mod \
 && grep -Fxq 'go 1.25.9' evmd/go.mod
RUN go mod download
RUN LEDGER_ENABLED=false COSMOS_BUILD_OPTIONS=staticlink BUILD_TAGS=muslc make build

FROM python:3.12-alpine
RUN apk add --no-cache bash curl jq build-base su-exec \
 && addgroup -g 1025 privi \
 && adduser -D -u 1025 -G privi privi
COPY --from=builder /src/build/evmd /usr/local/bin/evmd
COPY production-network/seven-validator/railway/main.py /opt/privi/main.py
ENV PYTHONUNBUFFERED=1
WORKDIR /opt/privi
# Railway mounts /data as root; bootstrap changes node ownership, validator drops privileges.
EXPOSE 26656 26657 8545 8099
ENTRYPOINT ["python", "/opt/privi/main.py"]
