// Standard Caddy entry point; no Workbench-specific proxy modules.
package main

import (
	"fmt"
	"os"
	_ "time/tzdata"

	caddycmd "github.com/caddyserver/caddy/v2/cmd"
	_ "github.com/caddyserver/caddy/v2/modules/standard"
)

func main() {
	if len(os.Args) == 2 && os.Args[1] == "--workbench-security-self-test" {
		if err := checkJOSEBackport(); err != nil {
			fmt.Fprintln(os.Stderr, err)
			os.Exit(1)
		}
		fmt.Println("CVE-2026-116587: JOSE v3 RSA bounds and public-header checks passed")
		return
	}
	caddycmd.Main()
}
