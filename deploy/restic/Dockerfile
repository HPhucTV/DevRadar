FROM golang:1.26.6-alpine3.23@sha256:e57c41c1d5864341031181b0db34b9a537bb5773eb6428e4e5bdaea0f9135406 AS builder

RUN apk add --no-cache ca-certificates curl tar

WORKDIR /src

RUN curl --fail --silent --show-error --location \
        --output /tmp/restic-0.19.1.tar.gz \
        https://github.com/restic/restic/releases/download/v0.19.1/restic-0.19.1.tar.gz \
    && echo "bb9b1a19040744d26d8a79be029d4e6b189c45ccc9d8831d7fe367d3c33df725  /tmp/restic-0.19.1.tar.gz" \
        | sha256sum -c - \
    && tar --extract --gzip --file /tmp/restic-0.19.1.tar.gz --strip-components=1 \
    && rm /tmp/restic-0.19.1.tar.gz

RUN go get golang.org/x/net@v0.56.0 \
        golang.org/x/text@v0.39.0 \
        google.golang.org/grpc@v1.82.1 \
    && go mod tidy \
    && go mod verify \
    && CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go run build.go \
    && mkdir -p /out \
    && cp /src/restic /out/restic \
    && /out/restic version | grep -E '^restic 0\.19\.1 '

FROM scratch

ENV HOME=/tmp \
    RESTIC_CACHE_DIR=/tmp/restic-cache

COPY --from=builder /out/restic /usr/bin/restic
COPY --from=builder /etc/ssl/certs/ca-certificates.crt /etc/ssl/certs/ca-certificates.crt

USER 65532:65532
WORKDIR /tmp

ENTRYPOINT ["/usr/bin/restic"]
