package position

import (
    "bytes"
    "crypto/ed25519"
    "crypto/rand"
    "crypto/sha256"
    "encoding/hex"
    "fmt"
    "testing"
)

func fixture(t *testing.T) (ed25519.PublicKey,[]Position) {
    t.Helper()
    pub,priv,err:=ed25519.GenerateKey(rand.Reader);if err!=nil {t.Fatal(err)}
    prev:=hex.EncodeToString(make([]byte,32))
    positions:=make([]Position,2)
    for i:=range positions {
        event:=sha256.Sum256([]byte(fmt.Sprintf("test-only reading %d",i)))
        p:=Position{ChainID:"privi-ci-pop-1",Company:"UTQ4JJ20",Zone:"GRID/READINGS",
            Sequence:uint64(i+1),Stamp:fmt.Sprintf("PoP:UTQ4JJ20:GRID/READINGS:%06d",i+1),
            PriorHash:prev,EventHash:hex.EncodeToString(event[:]),Signer:bytes.Clone(pub)}
        msg,err:=CanonicalMessage(p);if err!=nil{t.Fatal(err)}
        p.Signature=ed25519.Sign(priv,msg)
        buf:=new(bytes.Buffer)
        pack(buf,[]byte(domain+"_SEALED"));pack(buf,msg);pack(buf,p.Signature)
        h:=sha256.Sum256(buf.Bytes());p.BlockHash=hex.EncodeToString(h[:]);prev=p.BlockHash
        positions[i]=p
    }
    return pub,positions
}
func TestValidPoPChain(t *testing.T) {
    pub,records:=fixture(t)
    v,err:=VerifyChain(records,"privi-ci-pop-1",pub)
    if err!=nil||!v.PoPVerified||v.Records!=2||v.TipHash!=records[1].BlockHash {t.Fatalf("invalid verified position: %+v %v",v,err)}
}
func TestRejectTampering(t *testing.T) {
    tests:=map[string]func([]Position){
        "wrong chain":func(p []Position){p[1].ChainID="privi-ci-pop-2"},
        "wrong zone":func(p []Position){p[1].Zone="MARKET/TRADE"},
        "forged event":func(p []Position){p[1].EventHash=p[0].EventHash},
        "replay sequence":func(p []Position){p[1].Sequence=1},
        "missing ancestor":func(p []Position){p[1].PriorHash=p[0].PriorHash},
        "tampered seal":func(p []Position){p[1].BlockHash=p[0].BlockHash},
        "signature mutated":func(p []Position){p[1].Signature[0]^=1},
        "untrusted flag cannot substitute for signature":func(p []Position){p[1].Signature=nil},
    }
    for name,mutate:=range tests {t.Run(name,func(t *testing.T){
        pub,records:=fixture(t);mutate(records)
        if _,err:=VerifyChain(records,"privi-ci-pop-1",pub);err==nil {t.Fatal("accepted tampering")}
    })}
}
func TestRejectUnauthorizedAuthor(t *testing.T) {
    _,records:=fixture(t)
    other,_,err:=ed25519.GenerateKey(rand.Reader);if err!=nil {t.Fatal(err)}
    if _,err:=VerifyChain(records,"privi-ci-pop-1",other);err==nil {t.Fatal("accepted signer impersonation")}
}
func TestRejectMissingOrUnanchoredHistory(t *testing.T) {
    pub,records:=fixture(t)
    for _,slice:=range [][]Position{nil,records[1:]} {
        if _,err:=VerifyChain(slice,"privi-ci-pop-1",pub);err==nil {t.Fatal("accepted unanchored history")}
    }
}
