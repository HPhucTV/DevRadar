// Based on the Caddy v2.11.4 entrypoint:
// https://github.com/caddyserver/caddy/blob/v2.11.4/cmd/caddy/main.go
package main

import (
	_ "time/tzdata"

	caddycmd "github.com/caddyserver/caddy/v2/cmd"

	_ "github.com/caddyserver/caddy/v2/modules/standard"
)

func main() {
	caddycmd.Main()
}
