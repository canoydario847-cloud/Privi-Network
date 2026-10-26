# Privi Devnet: a single-validator Cosmos EVM chain (upstream cosmos/evm v0.7.3, evmd)
# with valueless TEST gas. It is the chain Privi Anchor writes its checkpoints to until
# the Privi mainnet launches. Not a financial network: TEST tokens have no value.

FROM golang:1.25.9-bookworm AS build
ARG EVM_VERSION=v0.7.3
RUN apt-get update && apt-get install -y --no-install-recommends git make gcc libc6-dev \
    && rm -rf /var/lib/apt/lists/*
RUN git clone --depth 1 --branch ${EVM_VERSION} https://github.com/cosmos/evm.git /src \
    && test "$(git -C /src describe --tags --exact-match)" = "${EVM_VERSION}"
WORKDIR /src/evmd
RUN go build -mod=readonly -trimpath -tags netgo \
      -ldflags "-w -s -X github.com/cosmos/cosmos-sdk/version.Name=evmd -X github.com/cosmos/cosmos-sdk/version.AppName=evmd -X github.com/cosmos/cosmos-sdk/version.Version=${EVM_VERSION}" \
      -o /out/evmd ./cmd/evmd \
    && /out/evmd version

FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends jq ca-certificates python3 curl \
    && rm -rf /var/lib/apt/lists/*
COPY --from=build /out/evmd /usr/local/bin/evmd
COPY entrypoint.sh /app/entrypoint.sh
COPY gateway.py bech32.py /app/
COPY web /app/web
RUN chmod +x /app/entrypoint.sh
ENV DEVNET_HOME=/data/evmd \
    DEVNET_COSMOS_CHAIN_ID=privi-devnet-1 \
    DEVNET_EVM_CHAIN_ID=772626 \
    PORT=10000
EXPOSE 10000
ENTRYPOINT ["/app/entrypoint.sh"]
