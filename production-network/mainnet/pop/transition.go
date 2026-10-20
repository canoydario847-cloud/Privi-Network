package position

import (
 "bytes"
 "crypto/ed25519"
 "crypto/sha256"
 "encoding/hex"
 "errors"
 "math"
)

// PositionHead is a proposed logical PoP head. It is not consensus state
// unless the application loads it from a trusted committed store.
type PositionHead struct {
 ChainID string
 Company string
 Zone string
 Sequence uint64
 TipHash string
}

// AdvancePosition validates a single append against a trusted previous head.
// The caller must authenticate both previous state and the authorized signer.
// This function does not persist state or implement BFT consensus.
func AdvancePosition(prev PositionHead, next Position, authorized ed25519.PublicKey) (PositionHead,error) {
 if prev.ChainID!=next.ChainID || prev.Company!=next.Company || prev.Zone!=next.Zone {
  return PositionHead{},errors.New("PoP head identity mismatch")
 }
 if prev.Sequence==math.MaxUint64 || next.Sequence!=prev.Sequence+1 {
  return PositionHead{},errors.New("PoP sequence gap or replay")
 }
 prior,err:=decodeHash(prev.TipHash)
 if err!=nil{return PositionHead{},err}
 zero:=make([]byte,sha256.Size)
 if (prev.Sequence==0)!=bytes.Equal(prior,zero) {
  return PositionHead{},errors.New("PoP head bootstrap or tip invalid")
 }
 if next.PriorHash!=prev.TipHash{return PositionHead{},errors.New("PoP tip mismatch")}
 if len(authorized)!=ed25519.PublicKeySize || !bytes.Equal(next.Signer,authorized) {
  return PositionHead{},errors.New("PoP author not authorized")
 }
 msg,err:=CanonicalMessage(next)
 if err!=nil{return PositionHead{},err}
 if len(next.Signature)!=ed25519.SignatureSize || !ed25519.Verify(authorized,msg,next.Signature) {
  return PositionHead{},errors.New("PoP invalid signature")
 }
 buf:=new(bytes.Buffer)
 pack(buf,[]byte(domain+"_SEALED"))
 pack(buf,msg)
 pack(buf,next.Signature)
 sum:=sha256.Sum256(buf.Bytes())
 sealed:=hex.EncodeToString(sum[:])
 if next.BlockHash!=sealed{return PositionHead{},errors.New("PoP seal mismatch")}
 return PositionHead{prev.ChainID,prev.Company,prev.Zone,next.Sequence,sealed},nil
}
