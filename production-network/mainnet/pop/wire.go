package position

// EVM-envelope codec for future native post-execution PoP validation. This
// codec does NOT establish successful Ethereum transaction execution, verify
// an EVM sender, or route data into ABCI FinalizeBlock by itself.
import (
    "bytes"
    "encoding/json"
    "errors"
)

const envelopePrefix = "PRIVI_POP_TX_V1\n"
const MaxEnvelopeBytes = 2048

// EncodeEnvelope yields an exact, length-bounded JSON encoding of one
// signed logical position. It never infers PRVI, USD, or sensor value.
// The caller must still verify the Ed25519 signature and prior hash against
// a consensus-backed authorized company/zone registry before commitment.
func EncodeEnvelope(position Position) ([]byte,error) {
    if _,err:=CanonicalMessage(position);err!=nil{return nil,err}
    if len(position.Signature)!=64 {
        return nil,errors.New("PoP envelope needs Ed25519 signature")
    }
    if _,err:=decodeHash(position.BlockHash);err!=nil{return nil,err}
    encoded,err:=json.Marshal(position)
    if err!=nil{return nil,err}
    out:=append([]byte(envelopePrefix),encoded...)
    if len(out)>MaxEnvelopeBytes {return nil,errors.New("PoP envelope too large")}
    return out,nil
}

// DecodeEnvelope is strict and rejects unknown fields, duplicate JSON keys,
// noncanonical escapes, alternative capitalization, whitespace, or trailing
// bytes, by requiring byte-for-byte equality against our sole canonical
// encoder. This does NOT authorize the signature or execute a position.
func DecodeEnvelope(raw []byte) (Position,error) {
    if len(raw)<=len(envelopePrefix)||len(raw)>MaxEnvelopeBytes||
        !bytes.HasPrefix(raw,[]byte(envelopePrefix)) {
        return Position{},errors.New("PoP transaction envelope prefix/size invalid")
    }
    var p Position
    if err:=json.Unmarshal(raw[len(envelopePrefix):],&p);err!=nil {
        return Position{},errors.New("PoP transaction envelope JSON malformed")
    }
    canonical,err:=EncodeEnvelope(p)
    if err!=nil{return Position{},err}
    if !bytes.Equal(raw,canonical) {
        return Position{},errors.New("PoP transaction envelope not canonical")
    }
    return p,nil
}
