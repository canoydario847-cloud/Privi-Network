# Valueless SINGLE-validator Cosmos EVM developer node for Railway, not mainnet.
FROM golang:1.25.9-alpine AS builder
RUN apk add --no-cache bash git build-base file linux-headers eudev-dev
WORKDIR /work
RUN git clone --depth 1 --branch v0.7.3 https://github.com/cosmos/evm.git /work \
 && test "$(git rev-parse HEAD)" = "c3ae9067a7eadcdea55a5192226916deb44c71c4"
RUN go mod download
RUN LEDGER_ENABLED=false COSMOS_BUILD_OPTIONS=staticlink BUILD_TAGS=muslc make build

FROM alpine:3.21
RUN apk add --no-cache bash jq ca-certificates su-exec \
 && addgroup -g 1025 nonroot && adduser -D -u 1025 -G nonroot nonroot
COPY --from=builder /work/build/evmd /usr/local/bin/evmd
COPY start.sh /usr/local/bin/start.sh
COPY start-node.sh /usr/local/bin/start-node.sh
RUN chmod 0755 /usr/local/bin/start.sh /usr/local/bin/start-node.sh /usr/local/bin/evmd
ENV PORT=8545
EXPOSE 8545
ENTRYPOINT ["/usr/local/bin/start.sh"]
