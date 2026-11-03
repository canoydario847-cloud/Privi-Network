# RELEASE BUILD RECIPE ONLY; cannot build without an independently reviewed
# release.patch and 64-hex SHA256. Never build a financial node from demo keys.
FROM golang:1.25.9-alpine AS build
RUN apk add --no-cache bash git ca-certificates
ARG UPSTREAM_COMMIT=c3ae9067a7eadcdea55a5192226916deb44c71c4
ARG REVIEWED_PATCH_SHA256
RUN set -eu; \
    test "$UPSTREAM_COMMIT" = "c3ae9067a7eadcdea55a5192226916deb44c71c4"; \
    git clone --quiet --no-checkout https://github.com/cosmos/evm.git /src/cosmos-evm; \
    git -C /src/cosmos-evm checkout --quiet "$UPSTREAM_COMMIT"; \
    test "$(git -C /src/cosmos-evm rev-parse HEAD)" = "$UPSTREAM_COMMIT"
# Place release.patch locally only AFTER a source audit and approved final IDs.
# No release.patch is included in the repo on purpose. Builds must fail otherwise.
COPY release.patch /tmp/release.patch
RUN set -eu; \
    test "${#REVIEWED_PATCH_SHA256}" = 64; \
    echo "$REVIEWED_PATCH_SHA256  /tmp/release.patch" | sha256sum -c -; \
    git -C /src/cosmos-evm apply --check /tmp/release.patch; \
    git -C /src/cosmos-evm apply /tmp/release.patch
WORKDIR /src/cosmos-evm/evmd
RUN CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build \
      -trimpath -ldflags="-s -w" -o /out/evmd ./cmd/evmd && \
    test -s /out/evmd

FROM alpine:3.22
RUN apk add --no-cache ca-certificates tzdata && \
    addgroup -S -g 1025 privi && \
    adduser -S -D -u 1025 -G privi privi
COPY --from=build --chown=1025:1025 /out/evmd /usr/local/bin/evmd
USER 1025:1025
WORKDIR /state
ENTRYPOINT ["/usr/local/bin/evmd"]
# DO NOT set a default CMD that would start a network.
