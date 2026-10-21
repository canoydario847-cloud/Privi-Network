package position

// Native PoP candidate state transitions using Cosmos SDK's consensus KVStore
// abstraction. A future custom app must MOUNT this store and call Apply
// atomically during ABCI execution. Not yet wired to production InitChain,
// transaction ante handlers or FinalizeBlock; NOT native PoP BFT finality.

import (
    "bytes"
    "context"
    "crypto/ed25519"
    "crypto/sha256"
    "encoding/binary"
    "encoding/hex"
    "encoding/json"
    "errors"
    "fmt"
    "sort"

    corestore "cosmossdk.io/core/store"
)

const StoreKey = "privi_pop"
const maxGenesisAuthorities = 256

var registryKey = []byte{0x01}
var ErrRegistryMissing = errors.New("PoP genesis authorization registry absent")
var ErrStateCorrupt = errors.New("PoP consensus state corrupt")
var ErrUnapprovedAuthor = errors.New("PoP company/zone author is not genesis-authorized")
var ErrSequence = errors.New("PoP sequence or prior position mismatch")

// Authority is a company+logical-zone public author key, not a validator,
// owner/treasury key, signature authority for mainnet, or proof of IoT origin.
type Authority struct {
    Company string `json:"company"`
    Zone string `json:"zone"`
    PublicKey []byte `json:"public_key"`
}
type registry struct {
    Version uint8 `json:"version"`
    ChainID string `json:"chain_id"`
    Authorities []Authority `json:"authorities"`
}
type Keeper struct { store corestore.KVStoreService }

func NewKeeper(store corestore.KVStoreService) (Keeper,error) {
    if store==nil {return Keeper{},errors.New("nil PoP consensus KVStoreService")}
    return Keeper{store:store},nil
}
func (k Keeper) kv(ctx context.Context) (corestore.KVStore,error) {
    if ctx==nil||k.store==nil {return nil,errors.New("PoP context or consensus store missing")}
    return k.store.OpenKVStore(ctx),nil
}
func validateAuthority(a Authority) error {
    if !companyPattern.MatchString(a.Company)||!zones[a.Zone]||len(a.PublicKey)!=ed25519.PublicKeySize {
        return errors.New("invalid PoP company/zone or Ed25519 author key")
    }
    return nil
}
func authorityKey(company,zone string) string {return company+"\x00"+zone}
func stateKey(company,zone string) []byte {
    return append([]byte{0x02},[]byte(authorityKey(company,zone))...)
}
func validateRegistry(r registry) error {
    if r.Version!=1||!chainPattern.MatchString(r.ChainID)||
        len(r.Authorities)<1||len(r.Authorities)>maxGenesisAuthorities {
        return ErrStateCorrupt
    }
    previous:=""
    for i,a:=range r.Authorities {
        if validateAuthority(a)!=nil {return ErrStateCorrupt}
        key:=authorityKey(a.Company,a.Zone)
        if i>0&&key<=previous {return ErrStateCorrupt}
        previous=key
    }
    return nil
}
func (k Keeper) loadRegistry(ctx context.Context) (registry,corestore.KVStore,error) {
    kv,err:=k.kv(ctx);if err!=nil{return registry{},nil,err}
    data,err:=kv.Get(registryKey)
    if err!=nil{return registry{},nil,err}
    if data==nil{return registry{},nil,ErrRegistryMissing}
    var r registry
    if err=json.Unmarshal(data,&r);err!=nil{return registry{},nil,ErrStateCorrupt}
    if err=validateRegistry(r);err!=nil{return registry{},nil,err}
    canonical,err:=json.Marshal(r)
    if err!=nil||!bytes.Equal(data,canonical){return registry{},nil,ErrStateCorrupt}
    return r,kv,nil
}

// InitGenesis stores one immutable, canonical authorization registry.
// The caller MUST execute in a rollback-capable cached InitChain SDK context,
// so any unexpected DB write failure aborts application initialization.
// No external call can register or revoke company keys after this point.
// Future key rotation needs a separately specified consensus transaction.
func canonicalGenesis(chainID string,entries []Authority) (registry,error) {
    r:=registry{Version:1,ChainID:chainID,Authorities:make([]Authority,len(entries))}
    for i,a:=range entries {
        r.Authorities[i]=Authority{Company:a.Company,Zone:a.Zone,PublicKey:bytes.Clone(a.PublicKey)}
    }
    sort.Slice(r.Authorities,func(i,j int)bool{
        a,b:=r.Authorities[i],r.Authorities[j]
        return authorityKey(a.Company,a.Zone)<authorityKey(b.Company,b.Zone)
    })
    if err:=validateRegistry(r);err!=nil{return registry{},fmt.Errorf("PoP genesis invalid: %w",err)}
    return r,nil
}
// ValidateGenesis is pure: the native app calls it BEFORE x/bank or other
// InitGenesis state transitions. Invalid signers or duplicate position
// authorities cannot trigger a partial SDK genesis initialization.
func ValidateGenesis(chainID string,entries []Authority) error {
    _,err:=canonicalGenesis(chainID,entries)
    return err
}
func (k Keeper) InitGenesis(ctx context.Context,chainID string,entries []Authority) error {
    r,err:=canonicalGenesis(chainID,entries);if err!=nil{return err}
    kv,err:=k.kv(ctx);if err!=nil{return err}
    existing,err:=kv.Get(registryKey);if err!=nil{return err}
    if existing!=nil {return errors.New("PoP genesis registry already initialized")}
    data,err:=json.Marshal(r);if err!=nil{return err}
    // Consensus-visible authorization is one atomic KV value. Never
    // write individual author entries before full genesis validation.
    return kv.Set(registryKey,data)
}
func (k Keeper) authorAndStore(ctx context.Context,p Position) (ed25519.PublicKey,corestore.KVStore,error) {
    r,kv,err:=k.loadRegistry(ctx);if err!=nil{return nil,nil,err}
    if p.ChainID!=r.ChainID{return nil,nil,errors.New("PoP chain ID differs from consensus genesis")}
    for _,a:=range r.Authorities {
        if a.Company==p.Company&&a.Zone==p.Zone {return ed25519.PublicKey(a.PublicKey),kv,nil}
    }
    return nil,nil,ErrUnapprovedAuthor
}

// readTip must reject corrupt/stale sequence state without altering it.
func readTip(kv corestore.KVStore,key []byte) (uint64,string,error) {
    raw,err:=kv.Get(key);if err!=nil{return 0,"",err}
    zero:=hex.EncodeToString(make([]byte,sha256.Size))
    if raw==nil{return 0,zero,nil}
    if len(raw)!=8+sha256.Size{return 0,"",ErrStateCorrupt}
    seq:=binary.BigEndian.Uint64(raw[:8])
    if seq==0{return 0,"",ErrStateCorrupt}
    hash:=raw[8:]
    if bytes.Equal(hash,make([]byte,sha256.Size)){return 0,"",ErrStateCorrupt}
    return seq,hex.EncodeToString(hash),nil
}

// Apply authenticates one next position against the consensus-backed
// genesis authority and persists its new sequence + tip in ONE KV write.
// SDK execution MUST ensure a failed call cannot commit partial transaction
// state; batch application and transaction routing are not yet implemented.
func (k Keeper) Apply(ctx context.Context,p Position) (Verified,error) {
    author,kv,err:=k.authorAndStore(ctx,p);if err!=nil{return Verified{},err}
    key:=stateKey(p.Company,p.Zone)
    seq,prior,err:=readTip(kv,key);if err!=nil{return Verified{},err}
    if seq==^uint64(0)||p.Sequence!=seq+1||p.PriorHash!=prior {
        return Verified{},ErrSequence
    }
    if !bytes.Equal(p.Signer,author) {return Verified{},ErrUnapprovedAuthor}
    message,err:=CanonicalMessage(p);if err!=nil{return Verified{},err}
    if len(p.Signature)!=ed25519.SignatureSize||!ed25519.Verify(author,message,p.Signature) {
        return Verified{},errors.New("PoP author signature invalid")
    }
    var seal bytes.Buffer
    pack(&seal,[]byte(domain+"_SEALED"))
    pack(&seal,message)
    pack(&seal,p.Signature)
    digest:=sha256.Sum256(seal.Bytes())
    want:=hex.EncodeToString(digest[:])
    if p.BlockHash!=want {return Verified{},errors.New("PoP sealed position hash mismatch")}
    state:=make([]byte,8+sha256.Size)
    binary.BigEndian.PutUint64(state[:8],p.Sequence)
    copy(state[8:],digest[:])
    if err=kv.Set(key,state);err!=nil{return Verified{},err}
    return Verified{PoPVerified:true,Stamp:p.Stamp,TipHash:want,Sequence:p.Sequence,Records:1},nil
}

// AssertInitialized must be called at each real ABCI block boundary.
// It rejects removal, corruption, or cross-chain replacement of the
// persisted PoP signer registry. This does not yet route PoP transactions
// through the Cosmos SDK execution pipeline.
func (k Keeper) AssertInitialized(ctx context.Context, expectedChain string) error {
   r,_,err:=k.loadRegistry(ctx)
   if err!=nil{return err}
   if !chainPattern.MatchString(expectedChain)||r.ChainID!=expectedChain {
       return errors.New("PoP committed registry chain identity mismatch")
   }
   return nil
}

// Snapshot is a bounded consensus-store read, NOT verification of BFT votes,
// sensor authenticity, treasury income or PoP economic value.
func (k Keeper) Snapshot(ctx context.Context,company,zone string) (uint64,string,error) {
    if validateAuthority(Authority{Company:company,Zone:zone,PublicKey:make([]byte,ed25519.PublicKeySize)})!=nil {
        return 0,"",ErrUnapprovedAuthor
    }
    r,kv,err:=k.loadRegistry(ctx);if err!=nil{return 0,"",err}
    found:=false
    for _,a:=range r.Authorities {if a.Company==company&&a.Zone==zone{found=true;break}}
    if !found {return 0,"",ErrUnapprovedAuthor}
    return readTip(kv,stateKey(company,zone))
}
