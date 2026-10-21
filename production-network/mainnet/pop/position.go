// Package position verifies the proposed Privi Point of Position (PoP)
// logical company/zone/sequence stamp and cryptographic hash linkage.
// This is an offline, keyless verifier prototype, NOT a BFT consensus engine,
// economic valuation proof, on-chain authorization registry or mainnet release.
package position

import (
    "bytes"
    "crypto/ed25519"
    "crypto/sha256"
    "encoding/binary"
    "encoding/hex"
    "errors"
    "fmt"
    "regexp"
)

const domain = "PRIVI_POP_POSITION_V1"
var companyPattern = regexp.MustCompile("^[A-Z0-9]{3,32}$")
var chainPattern = regexp.MustCompile("^[a-z][a-z0-9._-]{2,63}$")
var zones = map[string]bool{
    "ASSETS/VALUE":true, "WALLET/STAKE":true, "CONTRACTS":true,
    "WALLET/PAYROLL":true, "MARKET/MINT":true, "MARKET/TRADE":true,
    "DEVICES/ROBOTS/WALLET":true, "DAO/VOTE":true,
    "DEVICES/REGISTER":true, "AUTH/REGISTER":true,
    "FLEET/ASSETS":true, "GRID/READINGS":true, "NAV/PAGE":true,
    "TAB":true,
}

// Position is an externally supplied observation, NOT trusted or verified.
// The signature must be checked against a caller-supplied pinned authority.
// Its BlockHash is derived from the canonical signed bytes and signature.
type Position struct {
    ChainID string
    Company string
    Zone string
    Sequence uint64
    Stamp string
    PriorHash string
    EventHash string
    Signer []byte
    Signature []byte
    BlockHash string
}

// Verified is returned ONLY if every position from sequence 1 passes the
// signature, previous commitment, sequence and authority checks.
type Verified struct {
    PoPVerified bool
    Stamp string
    TipHash string
    Sequence uint64
    Records int
}

func decodeHash(s string) ([]byte,error) {
    if len(s)!=64 {return nil,errors.New("PoP hash must contain 64 lowercase hex characters")}
    b,err:=hex.DecodeString(s)
    if err!=nil || hex.EncodeToString(b)!=s {return nil,errors.New("PoP hash must be canonical lowercase hex")}
    return b,nil
}
func pack(b *bytes.Buffer, data []byte) {
    _ = binary.Write(b,binary.BigEndian,uint32(len(data)))
    _,_ = b.Write(data)
}
// CanonicalMessage is deterministic and length-prefixed to prevent ambiguous
// concatenations or stamp/zone substitution. It does NOT sign any data.
func CanonicalMessage(p Position) ([]byte,error) {
    if !chainPattern.MatchString(p.ChainID) {return nil,errors.New("invalid PoP chain identity")}
    if !companyPattern.MatchString(p.Company) {return nil,errors.New("invalid PoP company ID")}
    if !zones[p.Zone] {return nil,errors.New("unknown PoP zone")}
    if p.Sequence==0 {return nil,errors.New("PoP sequence must be positive")}
    want:=fmt.Sprintf("PoP:%s:%s:%06d",p.Company,p.Zone,p.Sequence)
    if p.Stamp!=want {return nil,errors.New("PoP stamp inconsistent with company, zone or sequence")}
    prior,err:=decodeHash(p.PriorHash);if err!=nil{return nil,err}
    event,err:=decodeHash(p.EventHash);if err!=nil{return nil,err}
    if len(p.Signer)!=ed25519.PublicKeySize {return nil,errors.New("invalid PoP author key")}
    buf:=new(bytes.Buffer)
    pack(buf,[]byte(domain))
    pack(buf,[]byte(p.ChainID))
    pack(buf,[]byte(p.Stamp))
    pack(buf,prior)
    pack(buf,event)
    pack(buf,p.Signer)
    return buf.Bytes(),nil
}

// SealedHash computes the canonical signed-record commitment. This verifies
// the shape of the signed message but NOT who is authorized to sign it.
// VerifyChain and the consensus-backed Keeper.Apply MUST independently verify
// the Ed25519 signature against their pinned authority before accepting this.
func SealedHash(p Position) (string,error) {
    message,err:=CanonicalMessage(p);if err!=nil{return "",err}
    if len(p.Signature)!=ed25519.SignatureSize {return "",errors.New("missing PoP record signature")}
    var seal bytes.Buffer
    pack(&seal,[]byte(domain+"_SEALED"))
    pack(&seal,message)
    pack(&seal,p.Signature)
    digest:=sha256.Sum256(seal.Bytes())
    return hex.EncodeToString(digest[:]),nil
}

// VerifyChain validates full ancestry from sequence 1 and an external pinned
// company signer. It deliberately does not assume a self-asserted
// pop_verified flag or confer token, dollar or consensus voting value.
func VerifyChain(records []Position,expectedChain string,authorized ed25519.PublicKey) (Verified,error) {
    if len(records)==0 || len(records)>10000 {return Verified{},errors.New("PoP evidence length must be 1..10000")}
    if !chainPattern.MatchString(expectedChain)||len(authorized)!=ed25519.PublicKeySize {
        return Verified{},errors.New("pinned PoP chain and author key required")
    }
    prev:="";var company,zone string
    for i,p:=range records {
        if p.ChainID!=expectedChain {return Verified{},errors.New("PoP cross-chain replay denied")}
        if i==0 {company,zone=p.Company,p.Zone} else if p.Company!=company||p.Zone!=zone {
            return Verified{},errors.New("PoP cannot cross company or zone histories")
        }
        if uint64(i)+1!=p.Sequence {return Verified{},errors.New("PoP sequence gap or replay")}
        if i==0 {prev=hex.EncodeToString(make([]byte,sha256.Size))}
        if p.PriorHash!=prev {return Verified{},errors.New("PoP previous hash mismatch")}
        if !bytes.Equal(p.Signer,authorized) {return Verified{},errors.New("PoP author not authorized by pinned key")}
        message,err:=CanonicalMessage(p);if err!=nil{return Verified{},err}
        if len(p.Signature)!=ed25519.SignatureSize||!ed25519.Verify(authorized,message,p.Signature) {
            return Verified{},errors.New("invalid PoP author signature")
        }
        // Use the same verified, domain-separated seal calculation for
        // offline ancestry checks as the consensus-backed native keeper.
        prev,err=SealedHash(p)
        if err!=nil{return Verified{},err}
        if p.BlockHash!=prev {return Verified{},errors.New("PoP block seal mismatch")}
    }
    return Verified{PoPVerified:true,Stamp:records[len(records)-1].Stamp,
        TipHash:prev,Sequence:records[len(records)-1].Sequence,Records:len(records)},nil
}
