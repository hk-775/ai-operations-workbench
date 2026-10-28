package main

import (
	"crypto/rand"
	"crypto/rsa"
	"encoding/json"
	"testing"

	jose "github.com/go-jose/go-jose/v3"
)

func TestJOSEBackportRejectsExpensiveRSAAndPrivateHeaders(t *testing.T) {
	if err := checkJOSEBackport(); err != nil {
		t.Fatal(err)
	}
}

func TestJOSEBackportPreservesValidKeysAndSignatures(t *testing.T) {
	key, err := rsa.GenerateKey(rand.Reader, 2048)
	if err != nil {
		t.Fatal(err)
	}
	for _, value := range []any{key, &key.PublicKey} {
		encoded, err := json.Marshal(jose.JSONWebKey{Key: value})
		if err != nil {
			t.Fatal(err)
		}
		var parsed jose.JSONWebKey
		if err := json.Unmarshal(encoded, &parsed); err != nil || !parsed.Valid() {
			t.Fatalf("valid key rejected: %v", err)
		}
	}
	signer, err := jose.NewSigner(jose.SigningKey{Algorithm: jose.RS256, Key: key}, nil)
	if err != nil {
		t.Fatal(err)
	}
	signed, err := signer.Sign([]byte("workbench proxy regression"))
	if err != nil {
		t.Fatal(err)
	}
	message, err := signed.CompactSerialize()
	if err != nil {
		t.Fatal(err)
	}
	parsed, err := jose.ParseSigned(message)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := parsed.Verify(&key.PublicKey); err != nil {
		t.Fatal(err)
	}
}
