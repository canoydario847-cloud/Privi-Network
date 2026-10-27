import hashlib
from fastapi.testclient import TestClient
from school import create_app

TOKEN="a-valid-test-token-longer-than-24"
SHA=hashlib.sha256(b"synthetic").hexdigest()
def api(tmp_path): return TestClient(create_app("sqlite:///"+str(tmp_path/"test.db"),TOKEN))
def post(c,path,data,token=TOKEN):
 return c.post(path,json=data,headers={"Authorization":"Bearer "+token})
def test_security_and_workflow(tmp_path):
 with api(tmp_path) as c:
  assert c.get("/health").status_code==200
  assert "Every agent" in c.get("/").text
  assert len(c.get("/courses").json()["courses"])==4
  assert post(c,"/agents",{"name":"Jose","operator":"Privi"},"bad").status_code==401
  aid=post(c,"/agents",{"name":"Jose","operator":"Privi"}).json()["agent_id"]
  dataset={"name":"synthetic","sha256":SHA,"reference":"s3://test/data","rights_confirmed":False}
  assert post(c,"/datasets",dataset).status_code==422
  dataset["rights_confirmed"]=True
  did=post(c,"/datasets",dataset).json()["dataset_id"]
  provider=post(c,"/providers",{"name":"planned GPU","category":"gpu"}).json()
  assert provider["hardware_connected"] is False
  run={"agent_id":aid,"dataset_id":did,"provider_id":provider["provider_id"],"kind":"training","budget_cents":0}
  assert post(c,"/runs",run).status_code==409
  answers={"quantum-foundations":[1,1,1],"agent-safety":[1,1,0],
           "data-governance":[1,0,1],"deployment-center":[1,0,1]}
  for course,solution in answers.items():
   assert post(c,f"/agents/{aid}/courses/{course}/assessment",{"answers":solution}).json()["passed"]
  assert c.get(f"/agents/{aid}/transcript",headers={"Authorization":"Bearer "+TOKEN}).json()["eligible"]
  created=post(c,"/runs",run).json()
  assert created["execution_started"] is False
  rid=created["run_id"]
  assert post(c,"/models",{"run_id":rid,"name":"Jose 1"}).status_code==409
  assert post(c,f"/runs/{rid}/result",{"status":"succeeded","provider_job":"demo"}).status_code==422
  report=post(c,f"/runs/{rid}/result",{"status":"succeeded","provider_job":"demo",
       "artifact_uri":"s3://test/model","artifact_sha256":SHA})
  assert report.status_code==200
  mid=post(c,"/models",{"run_id":rid,"name":"Jose 1"}).json()["model_id"]
  assert post(c,"/deployments",{"model_id":mid,"environment":"staging"}).status_code==409
  v=post(c,f"/models/{mid}/evaluations",{"metric":"accuracy","score":0.91,"minimum":0.8,"dataset_sha256":SHA})
  assert v.json()["passed"] and not v.json()["independently_verified"]
  dep=post(c,"/deployments",{"model_id":mid,"environment":"staging"}).json()
  assert dep["deployed"] is False
  approval=post(c,f"/deployments/{dep['deployment_id']}/approve",{"approver":"Owner"})
  assert approval.json()["state"]=="approved_not_deployed"
  prod=post(c,"/deployments",{"model_id":mid,"environment":"production"}).json()
  assert post(c,f"/deployments/{prod['deployment_id']}/approve",{"approver":"Owner"}).status_code==403
