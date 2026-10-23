// Package mintguard is an OFF-CHAIN prototype of fail-closed PRVI mint authorization.
// It is not connected to Cosmos SDK consensus state or the production bank keeper.
package mintguard

import (
 "errors"
 "math/big"
 "sync"
)

const MaximumBase = "1000000000000000000000000000"
var (
 ErrUnauthorized = errors.New("PRVI mint route is not authorized")
 ErrInvalid = errors.New("invalid positive base-unit amount")
 ErrCap = errors.New("PRVI lifetime issuance cap exceeded")
 ErrGenesis = errors.New("invalid genesis lifetime issuance")
)

type Guard struct {
 mu sync.Mutex
 lifetime *big.Int
 allowed map[string]struct{}
}
func parse(s string) (*big.Int,error) {
 if len(s)==0 || s[0]=='0' { return nil,ErrInvalid }
 for i:=0;i<len(s);i++ { if s[i]<'0'||s[i]>'9' {return nil,ErrInvalid} }
 n,ok:=new(big.Int).SetString(s,10)
 if !ok || n.Sign()<=0 {return nil,ErrInvalid}
 return n,nil
}
func ceiling() *big.Int {n,_:=new(big.Int).SetString(MaximumBase,10);return n}
// New creates a test-only guard. Caller names are not secure identities.
func New(genesis string, routes []string) (*Guard,error) {
 n,e:=parse(genesis);if e!=nil||n.Cmp(ceiling())>0 {return nil,ErrGenesis}
 allowed:=make(map[string]struct{},len(routes))
 for _,route:=range routes {if route=="" {return nil,ErrUnauthorized};allowed[route]=struct{}{}}
 return &Guard{lifetime:n,allowed:allowed},nil
}
// Issue invokes a callback after cap validation. A real keeper MUST use a
// single consensus cache context to roll back both bank and counter state.
func (g *Guard) Issue(route,amount string, mint func() error) error {
 if mint==nil {return ErrUnauthorized}
 n,e:=parse(amount);if e!=nil{return e}
 g.mu.Lock();defer g.mu.Unlock()
 if _,ok:=g.allowed[route];!ok{return ErrUnauthorized}
 next:=new(big.Int).Add(g.lifetime,n)
 if next.Cmp(ceiling())>0{return ErrCap}
 if e=mint();e!=nil{return e}
 g.lifetime=next
 return nil
}
func (g *Guard) Lifetime() string {g.mu.Lock();defer g.mu.Unlock();return g.lifetime.String()}
