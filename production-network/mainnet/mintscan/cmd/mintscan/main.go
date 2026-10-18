package main

import (
  "encoding/json"
  "flag"
  "fmt"
  "os"
  "os/exec"
  "strings"

  "github.com/canoydario847-cloud/Privi-Network/production-network/mainnet/mintscan"
)

func main() {
  root:=flag.String("root","","path to pinned cosmos/evm source root")
  flag.Parse()
  if *root=="" {fmt.Fprintln(os.Stderr,"--root is required");os.Exit(2)}
  tag,err:=exec.Command("git","-C",*root,"describe","--tags","--exact-match").Output()
  if err!=nil || strings.TrimSpace(string(tag))!=mintscan.UpstreamTag {
    fmt.Fprintln(os.Stderr,"REFUSED: expected exact reviewed cosmos/evm tag v0.7.3")
    os.Exit(2)
  }
  report,err:=mintscan.Scan(*root)
  data,_:=json.MarshalIndent(report,"","  ")
  fmt.Println(string(data))
  if err!=nil {
    fmt.Fprintln(os.Stderr,"PINNED SOURCE AUDIT FAILURE:",err)
    os.Exit(1)
  }
  fmt.Fprintln(os.Stderr,"SOURCE ROUTES ACCOUNTED FOR, BUT MAINNET IS STILL NO-GO")
}
