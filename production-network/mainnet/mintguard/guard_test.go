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
