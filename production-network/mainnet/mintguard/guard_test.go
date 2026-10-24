package mintguard
import ("errors";"testing")
func TestUnauthorizedNeverCallsBank(t *testing.T) {
 g,_:=New("1",[]string{"approved"});called:=false
 e:=g.Issue("erc20","2",func()error{called=true;return nil})
 if !errors.Is(e,ErrUnauthorized)||called||g.Lifetime()!="1"{t.Fatal("unauthorized issuance")}
}
func TestBankErrorLeavesCounterUnchanged(t *testing.T) {
 g,_:=New("1",[]string{"approved"});failure:=errors.New("bank rejected")
 e:=g.Issue("approved","2",func()error{return failure})
 if !errors.Is(e,failure)||g.Lifetime()!="1"{t.Fatal("non-atomic counter")}
}
func TestCapAndBurnBypass(t *testing.T) {
 g,_:=New(MaximumBase,[]string{"approved"});called:=false
 e:=g.Issue("approved","1",func()error{called=true;return nil})
 if !errors.Is(e,ErrCap)||called||g.Lifetime()!=MaximumBase{t.Fatal("cap bypass")}
}
func TestSuccessfulIssueAndInvalidInputs(t *testing.T) {
 g,_:=New("1",[]string{"approved"})
 for _,s:=range []string{"0","01","-1","1.0",""}{
  if !errors.Is(g.Issue("approved",s,func()error{return nil}),ErrInvalid){t.Fatal(s)}
 }
 if e:=g.Issue("approved","2",func()error{return nil});e!=nil||g.Lifetime()!="3"{t.Fatal(e)}
}

func TestZeroIssuanceGenesisAndPositiveMintOnly(t *testing.T) {
 g,err:=New("0",[]string{"approved"})
 if err!=nil || g.Lifetime()!="0" {t.Fatalf("zero genesis rejected: %v",err)}
 called:=false
 if err:=g.Issue("approved","0",func()error{called=true;return nil});!errors.Is(err,ErrInvalid)||called||g.Lifetime()!="0" {
  t.Fatalf("zero mint must be rejected without calling bank: %v",err)
 }
 if err:=g.Issue("approved","1",func()error{called=true;return nil});err!=nil||!called||g.Lifetime()!="1" {
  t.Fatalf("positive mint after zero genesis rejected: %v",err)
 }
 for _,bad:=range []string{"","00","01","-1","1.0"} {
  if _,err:=New(bad,[]string{"approved"});!errors.Is(err,ErrGenesis) {
   t.Fatalf("invalid genesis %q accepted: %v",bad,err)
  }
 }
}
