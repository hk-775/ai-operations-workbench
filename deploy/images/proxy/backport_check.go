package main

import (
	"encoding/base64"
	"encoding/json"
	"fmt"
	"math/big"
	"strings"

	jose "github.com/go-jose/go-jose/v3"
)

// Exercise the library linked into this binary before issuing image-specific VEX.
// The modulus check runs first, so an unpatched binary fails before the costly case.
func checkJOSEBackport() error {
	encode := func(n *big.Int) string { return base64.RawURLEncoding.EncodeToString(n.Bytes()) }
	key := map[string]string{"kty": "RSA", "e": "AQAB",
		"n": encode(new(big.Int).Lsh(big.NewInt(1), 4096))}
	check := func(expected string) error {
		data, err := json.Marshal(key)
		if err != nil {
			return err
		}
		var parsed jose.JSONWebKey
		if err = json.Unmarshal(data, &parsed); err == nil || !strings.Contains(err.Error(), expected) {
			return fmt.Errorf("JOSE backport check failed: %s", expected)
		}
		return nil
	}
	if err := check("modulus too large"); err != nil {
		return err
	}
	key["n"] = encode(new(big.Int).Lsh(big.NewInt(1), 2047))
	key["d"], key["q"] = "Aw", "Aw"
	key["p"] = encode(new(big.Int).Lsh(big.NewInt(1), 16383))
	if err := check("p * q != n"); err != nil {
		return err
	}
	header, _ := json.Marshal(map[string]any{"alg": "RS256", "jwk": key})
	message := base64.RawURLEncoding.EncodeToString(header) + ".e30.AQ"
	if _, err := jose.ParseSigned(message); err == nil || !strings.Contains(err.Error(), "private parameters") {
		return fmt.Errorf("JOSE backport check failed: private JWS header")
	}
	return nil
}
