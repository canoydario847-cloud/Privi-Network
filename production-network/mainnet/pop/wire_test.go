package position

import (
    "bytes"
    "testing"
)

func TestEnvelopeRoundtripFromSignedPosition(t *testing.T) {
    pub,records:=fixture(t)
    wire,err:=EncodeEnvelope(records[0])
    if err!=nil {t.Fatal(err)}
    recovered,err:=DecodeEnvelope(wire)
    if err!=nil||recovered.Stamp!=records[0].Stamp||recovered.EventHash!=records[0].EventHash {
        t.Fatalf("signed PoP wire roundtrip: %+v %v",recovered,err)
    }
    if _,err:=VerifyChain([]Position{recovered},"privi-ci-pop-1",pub);err!=nil {
        t.Fatalf("decoded position must still pass full authorized signature/hash check: %v",err)
    }
    if len(wire)>MaxEnvelopeBytes {t.Fatal("valid envelope exceeded cap")}
}
func TestEnvelopeRejectsNonCanonicalVariants(t *testing.T) {
    _,records:=fixture(t)
    canonical,err:=EncodeEnvelope(records[0]);if err!=nil{t.Fatal(err)}
    variants:=map[string][]byte{
        "missing magic":bytes.TrimPrefix(canonical,[]byte(envelopePrefix)),
        "extra leading byte":append([]byte("X"),canonical...),
        "trailing whitespace":append(bytes.Clone(canonical),byte(' ')),
        "oversized payload":append(bytes.Clone(canonical),bytes.Repeat([]byte("X"),MaxEnvelopeBytes)...),
        "empty":nil,
    }
    first:=bytes.IndexByte(canonical,byte('{'))
    if first<0 {t.Fatal("canonical JSON not found")}
    variants["unnecessary leading JSON space"]=append(
        append(bytes.Clone(canonical[:first]),byte(' ')),canonical[first:]...)
    // Duplicated JSON property is valid to many parsers; not here.
    variants["duplicate property"]=append(
        bytes.Clone(canonical[:len(canonical)-1]),[]byte(",\"ChainID\":\"privi-ci-pop-1\"}")...)
    // Unknown field must never be treated as an on-chain security assertion.
    variants["forged verified flag"]=append(
        bytes.Clone(canonical[:len(canonical)-1]),[]byte(",\"PoPVerified\":true}")...)
    // Changing the stamp without changing the cryptographic signature is a
    // canonical decode, but Apply/VerifyChain must still reject it.
    for name,payload:=range variants {
        t.Run(name,func(t *testing.T){
            if _,err:=DecodeEnvelope(payload);err==nil{t.Fatal("non-canonical envelope accepted")}
        })
    }
}
func TestEnvelopeRejectsMalformedPositionAndMissingSig(t *testing.T) {
    _,records:=fixture(t)
    bad:=records[0]
    bad.Signature=nil
    if _,err:=EncodeEnvelope(bad);err==nil{t.Fatal("signed record without signature encoded")}
    bad=records[0];bad.BlockHash="not-a-hash"
    if _,err:=EncodeEnvelope(bad);err==nil{t.Fatal("invalid seal encoded")}
    bad=records[0];bad.Stamp="PoP:UTQ4JJ20:GRID/READINGS:000999"
    if _,err:=EncodeEnvelope(bad);err==nil{t.Fatal("inconsistent stamp encoded")}
}
