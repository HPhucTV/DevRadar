FROM golang:1.26.6-alpine3.23@sha256:e57c41c1d5864341031181b0db34b9a537bb5773eb6428e4e5bdaea0f9135406 AS builder

RUN apk add --no-cache ca-certificates git

WORKDIR /build

COPY main.go ./

# Build the released Caddy source as a dependency so version metadata is kept.
# The three explicit upgrades are the minimum versions that clear the current
# fixable advisory set in the official stable image.
RUN go mod init devradar/caddy \
    && go get github.com/caddyserver/caddy/v2@v2.11.4 \
    && go get golang.org/x/net@v0.56.0 \
        golang.org/x/text@v0.39.0 \
        google.golang.org/grpc@v1.82.1 \
    && go mod tidy \
    && go list -m all | grep -Fx 'golang.org/x/net v0.56.0' \
    && go list -m all | grep -Fx 'golang.org/x/text v0.39.0' \
    && go list -m all | grep -Fx 'google.golang.org/grpc v1.82.1' \
    && go mod verify \
    && CGO_ENABLED=0 go build \
        -tags=nobadger,nomysql,nopgx \
        -trimpath \
        -ldflags="-s -w" \
        -o /out/caddy \
        . \
    && /out/caddy version | grep -E '^v2\.11\.4 h1:[A-Za-z0-9+/=]+$'

COPY Caddyfile /rootfs/etc/caddy/Caddyfile

RUN mkdir -p /rootfs/data/caddy /rootfs/config/caddy \
    && touch /rootfs/data/caddy/.keep /rootfs/config/caddy/.keep \
    && chown -R 10001:10001 /rootfs/data /rootfs/config

FROM scratch

ENV XDG_CONFIG_HOME=/config \
    XDG_DATA_HOME=/data

COPY --from=builder /out/caddy /usr/bin/caddy
COPY --from=builder /etc/ssl/certs/ca-certificates.crt /etc/ssl/certs/ca-certificates.crt
COPY --from=builder /rootfs/etc/caddy /etc/caddy
COPY --from=builder --chown=10001:10001 /rootfs/data /data
COPY --from=builder --chown=10001:10001 /rootfs/config /config

USER 10001:10001
WORKDIR /srv

EXPOSE 8080 8443 8443/udp

ENTRYPOINT ["/usr/bin/caddy"]
CMD ["run", "--config", "/etc/caddy/Caddyfile", "--adapter", "caddyfile"]
