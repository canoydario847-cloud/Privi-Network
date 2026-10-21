package position

import (
    "bytes"
    "context"
    "crypto/ed25519"
    "crypto/rand"
    "crypto/sha256"
    "encoding/hex"
    "errors"
    "fmt"
    "testing"

    corestore "cosmossdk.io/core/store"
)
type mockKV struct {
    entries map[string][]byte
    readError error
    writeError error
}
func newMockKV() *mockKV {return &mockKV{entries:map[string][]byte{}}}
func (m *mockKV) Get(key []byte)([]byte,error){
    if m.readError!=nil{return nil,m.readError}
    return bytes.Clone(m.entries[string(key)]),nil
}
func (m *mockKV) Set(key,value []byte)error{
    if m.writeError!=nil{return m.writeError}
    m.entries[string(key)]=bytes.Clone(value);return nil
}
func (m *mockKV) Has(key []byte)(bool,error){v,e:=m.Get(key);return v!=nil,e}
func (m *mockKV) Delete(key []byte)error{delete(m.entries,string(key));return nil}
func (*mockKV) Iterator([]byte,[]byte)(corestore.Iterator,error){return nil,errors.New("unused test iterator")}
func (*mockKV) ReverseIterator([]byte,[]byte)(corestore.Iterator,error){return nil,errors.New("unused test iterator")}
type mockService struct{kv *mockKV}
func (m mockService) OpenKVStore(context.Context)corestore.KVStore{return m.kv}

func setupPosition(t *testing.T)(Keeper,*mockKV,ed25519.PublicKey,ed25519.PrivateKey) {
    t.Helper()
    pub,priv,err:=ed25519.GenerateKey(rand.Reader);if err!=nil{t.Fatal(err)}
    db:=newMockKV();k,err:=NewKeeper(mockService{db});if err!=nil{t.Fatal(err)}
    if err:=k.InitGenesis(context.Background(),"privi-ci-pop-1",[]Authority{
        {Company:"UTQ4JJ20",Zone:"GRID/READINGS",PublicKey:pub},
    });err!=nil{t.Fatal(err)}
    return k,db,pub,priv
}
func makePosition(t *testing.T,priv ed25519.PrivateKey,seq uint64,previous string)Position{
    t.Helper()
    event:=sha256.Sum256([]byte(fmt.Sprintf("signed PoP telemetry %d",seq)))
    p:=Position{ChainID:"privi-ci-pop-1",Company:"UTQ4JJ20",Zone:"GRID/READINGS",
        Sequence:seq,Stamp:fmt.Sprintf("PoP:UTQ4JJ20:GRID/READINGS:%06d",seq),
        PriorHash:previous,EventHash:hex.EncodeToString(event[:]),
        Signer:bytes.Clone(priv.Public().(ed25519.PublicKey))}
    msg,err:=CanonicalMessage(p);if err!=nil{t.Fatal(err)}
    p.Signature=ed25519.Sign(priv,msg)
    var buf bytes.Buffer
    pack(&buf,[]byte(domain+"_SEALED"));pack(&buf,msg);pack(&buf,p.Signature)
    h:=sha256.Sum256(buf.Bytes());p.BlockHash=hex.EncodeToString(h[:])
    return p
}
func zeroTip()string{return hex.EncodeToString(make([]byte,sha256.Size))}
func TestKeeperTwoTransitionsAcrossRestart(t *testing.T){
    k,db,pub,priv:=setupPosition(t);ctx:=context.Background()
    first:=makePosition(t,priv,1,zeroTip())
    out,err:=k.Apply(ctx,first)
    if err!=nil||!out.PoPVerified||out.Sequence!=1{t.Fatalf("first application %v %+v",err,out)}
    // A new keeper on the same consensus KV store observes the immutable
    // registry and persistent tip instead of resetting position sequence.
    restarted,err:=NewKeeper(mockService{db});if err!=nil{t.Fatal(err)}
    seq,tip,err:=restarted.Snapshot(ctx,"UTQ4JJ20","GRID/READINGS")
    if err!=nil||seq!=1||tip!=first.BlockHash{t.Fatalf("restart tip %d %s %v",seq,tip,err)}
    second:=makePosition(t,priv,2,tip)
    result,err:=restarted.Apply(ctx,second)
    if err!=nil||result.Sequence!=2||result.TipHash!=second.BlockHash{
        t.Fatalf("second application %v %+v",err,result)
    }
    if _,err:=restarted.Apply(ctx,second);!errors.Is(err,ErrSequence){t.Fatalf("replay accepted: %v",err)}
    if _,err:=restarted.Apply(ctx,first);!errors.Is(err,ErrSequence){t.Fatalf("stale replay accepted: %v",err)}
    if seq,tip,err=restarted.Snapshot(ctx,"UTQ4JJ20","GRID/READINGS");err!=nil||seq!=2||tip!=second.BlockHash{
        t.Fatalf("replay mutated persisted state: %d %s %v",seq,tip,err)
    }
    if !bytes.Equal(pub,first.Signer){t.Fatal("unexpected signer")}
}
// Batch verification must be atomic for one native PoP company-zone stream.
// A valid first record must never be stored if the second is forged.
func TestKeeperAtomicBatchCommitsOneVerifiedTip(t *testing.T) {
    k,db,_,priv:=setupPosition(t)
    ctx:=context.Background()
    first:=makePosition(t,priv,1,zeroTip())
    second:=makePosition(t,priv,2,first.BlockHash)
    result,err:=k.ApplyBatch(ctx,[]Position{first,second})
    if err!=nil||!result.PoPVerified||result.Records!=2||result.Sequence!=2||
        result.TipHash!=second.BlockHash {
        t.Fatalf("valid PoP batch failed: result=%+v err=%v",result,err)
    }
    if len(db.entries)!=2 {t.Fatalf("expected immutable registry and ONE position tip, got %d keys",len(db.entries))}
    restarted,err:=NewKeeper(mockService{db});if err!=nil{t.Fatal(err)}
    seq,tip,err:=restarted.Snapshot(ctx,"UTQ4JJ20","GRID/READINGS")
    if err!=nil||seq!=2||tip!=second.BlockHash {t.Fatalf("batch not durable after keeper restart: %d %s %v",seq,tip,err)}
    if _,err:=restarted.ApplyBatch(ctx,[]Position{first,second});!errors.Is(err,ErrSequence) {
        t.Fatalf("accepted replayed PoP batch: %v",err)
    }
    third:=makePosition(t,priv,3,second.BlockHash)
    if out,err:=restarted.Apply(ctx,third);err!=nil||out.Sequence!=3||out.Records!=1{
        t.Fatalf("single-position API broke after batch: %+v %v",out,err)
    }
}

func TestKeeperAtomicBatchRejectsForgedLaterRecordWithoutPartialWrite(t *testing.T) {
    mutators:=map[string]func(*Position){
        "forged signature":func(p *Position){p.Signature[0]^=1},
        "changed event hash":func(p *Position){p.EventHash="f"+p.EventHash[1:]},
        "sequence gap":func(p *Position){p.Sequence=3},
        "replayed sequence":func(p *Position){p.Sequence=1},
        "wrong prior tip":func(p *Position){p.PriorHash=zeroTip()},
        "different company":func(p *Position){p.Company="ATTACKER"},
        "different zone":func(p *Position){p.Zone="FLEET/ASSETS"},
        "cross-chain record":func(p *Position){p.ChainID="privi-other-1"},
    }
    for name,mutate:=range mutators {
        t.Run(name,func(t *testing.T) {
            k,db,_,priv:=setupPosition(t);ctx:=context.Background()
            first:=makePosition(t,priv,1,zeroTip())
            second:=makePosition(t,priv,2,first.BlockHash)
            mutate(&second)
            if _,err:=k.ApplyBatch(ctx,[]Position{first,second});err==nil {
                t.Fatal("invalid second record accepted in atomic PoP batch")
            }
            seq,tip,err:=k.Snapshot(ctx,"UTQ4JJ20","GRID/READINGS")
            if err!=nil||seq!=0||tip!=zeroTip() {
                t.Fatalf("invalid batch partially advanced PoP state: %d %s %v",seq,tip,err)
            }
            if len(db.entries)!=1 {t.Fatal("invalid batch wrote more than genesis registry")}
            valid:=makePosition(t,priv,2,first.BlockHash)
            if _,err:=k.ApplyBatch(ctx,[]Position{first,valid});err!=nil {
                t.Fatalf("rejected valid retry after invalid batch: %v",err)
            }
        })
    }
}

func TestKeeperAtomicBatchSizeAndStoreWriteFailure(t *testing.T) {
    k,db,_,priv:=setupPosition(t);ctx:=context.Background()
    if _,err:=k.ApplyBatch(ctx,nil);err==nil{t.Fatal("accepted empty batch")}
    oversized:=make([]Position,129)
    if _,err:=k.ApplyBatch(ctx,oversized);err==nil{t.Fatal("accepted unbounded batch")}
    first:=makePosition(t,priv,1,zeroTip())
    second:=makePosition(t,priv,2,first.BlockHash)
    db.writeError=errors.New("disposable storage write unavailable")
    if _,err:=k.ApplyBatch(ctx,[]Position{first,second});err==nil {
        t.Fatal("swallowed batch KV write error")
    }
    db.writeError=nil
    seq,tip,err:=k.Snapshot(ctx,"UTQ4JJ20","GRID/READINGS")
    if err!=nil||seq!=0||tip!=zeroTip() {
        t.Fatalf("failed batch KV write advanced sequence: %d %s %v",seq,tip,err)
    }
    if _,err:=k.ApplyBatch(ctx,[]Position{first,second});err!=nil{
        t.Fatalf("valid batch could not retry after storage recovery: %v",err)
    }
}

func TestKeeperFailsClosedOnWrongIdentityOrTampering(t *testing.T){
    for name,mutate:=range map[string]func(*Position){
        "wrong chain":func(p *Position){p.ChainID="privi-other-1"},
        "wrong company":func(p *Position){p.Company="MALICIOUS"},
        "wrong zone":func(p *Position){p.Zone="MARKET/TRADE"},
        "sequence gap":func(p *Position){p.Sequence=2},
        "wrong ancestor":func(p *Position){p.PriorHash="f"+zeroTip()[1:]},
        "event substitution":func(p *Position){if p.EventHash[0]=='0'{p.EventHash="1"+p.EventHash[1:]}else{p.EventHash="0"+p.EventHash[1:]}},
        "forged signature":func(p *Position){p.Signature[0]^=1},
        "forged seal":func(p *Position){if p.BlockHash[0]=='f'{p.BlockHash="0"+p.BlockHash[1:]}else{p.BlockHash="f"+p.BlockHash[1:]}},
        "missing signature":func(p *Position){p.Signature=nil},
    }{
        t.Run(name,func(t *testing.T){
            k,db,_,priv:=setupPosition(t)
            p:=makePosition(t,priv,1,zeroTip());mutate(&p)
            if _,err:=k.Apply(context.Background(),p);err==nil{t.Fatal("accepted invalid PoP transition")}
            if len(db.entries)!=1{t.Fatal("invalid PoP wrote consensus state")}
        })
    }
}
func TestKeeperDoesNotTrustSelfSignedUnregisteredAuthor(t *testing.T){
    k,db,_,_:=setupPosition(t)
    _,attacker,err:=ed25519.GenerateKey(rand.Reader);if err!=nil{t.Fatal(err)}
    p:=makePosition(t,attacker,1,zeroTip())
    if _,err=k.Apply(context.Background(),p);!errors.Is(err,ErrUnapprovedAuthor){
        t.Fatalf("self-approved author accepted: %v",err)
    }
    if len(db.entries)!=1{t.Fatal("attacker changed state")}
}
func TestKeeperGenesisImmutableAndUnique(t *testing.T){
    k,db,pub,_:=setupPosition(t)
    ctx:=context.Background()
    if err:=k.InitGenesis(ctx,"privi-ci-pop-1",[]Authority{{Company:"ATTACKER",Zone:"NAV/PAGE",PublicKey:pub}});err==nil{
        t.Fatal("post-genesis author enrollment accepted")
    }
    if len(db.entries)!=1{t.Fatal("unexpected post-genesis KV mutation")}
    fresh:=newMockKV();newKeeper,_:=NewKeeper(mockService{fresh})
    repeated:=[]Authority{
        {Company:"UTQ4JJ20",Zone:"GRID/READINGS",PublicKey:pub},
        {Company:"UTQ4JJ20",Zone:"GRID/READINGS",PublicKey:pub},
    }
    if err:=newKeeper.InitGenesis(ctx,"privi-ci-pop-1",repeated);err==nil{t.Fatal("duplicate company/zone accepted")}
    if len(fresh.entries)!=0{t.Fatal("invalid registry partially initialized")}
    if err:=newKeeper.InitGenesis(ctx,"privi-ci-pop-1",nil);err==nil{t.Fatal("empty registry accepted")}
    if len(fresh.entries)!=0{t.Fatal("empty registry wrote state")}
}
func TestKeeperRejectsMissingAndCorruptConsensusState(t *testing.T){
    db:=newMockKV();k,_:=NewKeeper(mockService{db})
    _,priv,err:=ed25519.GenerateKey(rand.Reader);if err!=nil{t.Fatal(err)}
    p:=makePosition(t,priv,1,zeroTip())
    if _,err:=k.Apply(context.Background(),p);!errors.Is(err,ErrRegistryMissing){t.Fatal(err)}
    for _,corrupt:=range []string{"{","{}","{\"version\":1,\"chain_id\":\"privi-ci-pop-1\",\"authorities\":[]}"}{
        db.entries[string(registryKey)]=[]byte(corrupt)
        if _,err:=k.Apply(context.Background(),p);!errors.Is(err,ErrStateCorrupt){t.Fatalf("accepted registry corruption: %v",err)}
    }
    k,db,_,priv=setupPosition(t)
    db.entries[string(stateKey("UTQ4JJ20","GRID/READINGS"))]=[]byte("corrupt")
    if _,err:=k.Apply(context.Background(),makePosition(t,priv,1,zeroTip()));!errors.Is(err,ErrStateCorrupt){t.Fatal(err)}
}
func TestKeeperFailedWriteDoesNotAdvanceSequence(t *testing.T){
    k,db,_,priv:=setupPosition(t);ctx:=context.Background()
    db.writeError=errors.New("disk unavailable")
    if _,err:=k.Apply(ctx,makePosition(t,priv,1,zeroTip()));err==nil{t.Fatal("ignored disk failure")}
    db.writeError=nil
    seq,tip,err:=k.Snapshot(ctx,"UTQ4JJ20","GRID/READINGS")
    if err!=nil||seq!=0||tip!=zeroTip(){t.Fatalf("failed write changed state: %v %d %s",err,seq,tip)}
}
func TestKeeperNilStoreAndContextRejected(t *testing.T){
    if _,err:=NewKeeper(nil);err==nil{t.Fatal("nil consensus store accepted")}
    k,_,_,priv:=setupPosition(t)
    if _,err:=k.Apply(nil,makePosition(t,priv,1,zeroTip()));err==nil{t.Fatal("nil context accepted")}
}

func TestAssertInitializedBlocksRegistryRemovalAndCrossChain(t *testing.T) {
    k,db,_,_:=setupPosition(t)
    ctx:=context.Background()
    if err:=k.AssertInitialized(ctx,"privi-ci-pop-1");err!=nil {
        t.Fatalf("valid PoP registry rejected: %v",err)
    }
    if err:=k.AssertInitialized(ctx,"privi-foreign-1");err==nil {
        t.Fatal("cross-chain PoP registry passed block-boundary verification")
    }
    original:=bytes.Clone(db.entries[string(registryKey)])
    delete(db.entries,string(registryKey))
    if err:=k.AssertInitialized(ctx,"privi-ci-pop-1");!errors.Is(err,ErrRegistryMissing){
        t.Fatalf("missing registry passed block boundary: %v",err)
    }
    db.entries[string(registryKey)]=[]byte("corrupt")
    if err:=k.AssertInitialized(ctx,"privi-ci-pop-1");!errors.Is(err,ErrStateCorrupt){
        t.Fatalf("corrupt registry passed block boundary: %v",err)
    }
    db.entries[string(registryKey)]=original
    if err:=k.AssertInitialized(ctx,"privi-ci-pop-1");err!=nil {
        t.Fatalf("restored valid registry rejected: %v",err)
    }
}
