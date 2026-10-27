"""Privi Quantum School: guarded metadata registry. No GPU/QPU execution occurs."""
import hashlib
import hmac
import os
import uuid
from datetime import datetime, timezone
from typing import Literal

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, JSON, String, create_engine, select, text
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

COURSES = {
 "quantum-foundations": {"title":"Quantum and Classical Foundations",
  "lessons":["A quantum processor is not universally faster","Simulation is not a hardware QPU run","Verify provider execution separately"],
  "quiz":[("Can every AI model run faster on a QPU?",["Yes","No"],1),("Does simulation prove hardware execution?",["Yes","No"],1),("Which confirms a QPU result?",["A badge","An authenticated provider receipt"],1)]},
 "agent-safety": {"title":"Agent Safety and Authorization",
  "lessons":["Least-privilege credentials","Approvals differ from outcomes","A signature only proves a signed assertion"],
  "quiz":[("Should secrets be stored in training data?",["Yes","No"],1),("Does approval prove execution?",["Yes","No"],1),("Must production releases require an owner?",["Yes","No"],0)]},
 "data-governance": {"title":"Dataset Rights and Model Provenance",
  "lessons":["Document data rights","Record dataset and artifact digests","Evaluate model claims carefully"],
  "quiz":[("May you use a dataset without rights?",["Yes","No"],1),("Should dataset lineage be recorded?",["Yes","No"],0),("Is self-reported accuracy independently audited?",["Yes","No"],1)]},
 "deployment-center": {"title":"Cloud Deployment and Cost Control",
  "lessons":["Budget caps and provider authorization","Evaluation before release","Approval is not deployment"],
  "quiz":[("Can a pending job count as trained?",["Yes","No"],1),("Should models pass evaluation before release?",["Yes","No"],0),("Does approved mean deployed?",["Yes","No"],1)]},
}
DIGEST = "^[0-9a-f]{64}$"
def new_id(): return uuid.uuid4().hex
def now(): return datetime.now(timezone.utc)

class Base(DeclarativeBase): pass
class Agent(Base):
 __tablename__="qschool_agents"
 id:Mapped[str]=mapped_column(String(32),primary_key=True)
 name:Mapped[str]=mapped_column(String(100))
 operator:Mapped[str]=mapped_column(String(100))
class Pass(Base):
 __tablename__="qschool_passes"
 id:Mapped[str]=mapped_column(String(32),primary_key=True)
 agent:Mapped[str]=mapped_column(String(32),ForeignKey("qschool_agents.id"))
 course:Mapped[str]=mapped_column(String(50))
 score:Mapped[int]=mapped_column(Integer)
class Dataset(Base):
 __tablename__="qschool_datasets"
 id:Mapped[str]=mapped_column(String(32),primary_key=True)
 name:Mapped[str]=mapped_column(String(100))
 sha256:Mapped[str]=mapped_column(String(64))
 reference:Mapped[str]=mapped_column(String(500))
 rights:Mapped[bool]=mapped_column(Boolean)
class Provider(Base):
 __tablename__="qschool_providers"
 id:Mapped[str]=mapped_column(String(32),primary_key=True)
 name:Mapped[str]=mapped_column(String(100))
 category:Mapped[str]=mapped_column(String(20))
class Run(Base):
 __tablename__="qschool_runs"
 id:Mapped[str]=mapped_column(String(32),primary_key=True)
 agent:Mapped[str]=mapped_column(String(32),ForeignKey("qschool_agents.id"))
 dataset:Mapped[str]=mapped_column(String(32),ForeignKey("qschool_datasets.id"))
 provider:Mapped[str]=mapped_column(String(32),ForeignKey("qschool_providers.id"))
 kind:Mapped[str]=mapped_column(String(30))
 budget_cents:Mapped[int]=mapped_column(Integer)
 status:Mapped[str]=mapped_column(String(40),default="awaiting_external_executor")
 provider_job:Mapped[str|None]=mapped_column(String(200),nullable=True)
 artifact_uri:Mapped[str|None]=mapped_column(String(500),nullable=True)
 artifact_sha256:Mapped[str|None]=mapped_column(String(64),nullable=True)
class Model(Base):
 __tablename__="qschool_models"
 id:Mapped[str]=mapped_column(String(32),primary_key=True)
 run:Mapped[str]=mapped_column(String(32),ForeignKey("qschool_runs.id"),unique=True)
 name:Mapped[str]=mapped_column(String(100))
class Eval(Base):
 __tablename__="qschool_evaluations"
 id:Mapped[str]=mapped_column(String(32),primary_key=True)
 model:Mapped[str]=mapped_column(String(32),ForeignKey("qschool_models.id"))
 metric:Mapped[str]=mapped_column(String(100))
 score:Mapped[float]=mapped_column(Float)
 minimum:Mapped[float]=mapped_column(Float)
 evaluation_dataset_sha256:Mapped[str]=mapped_column(String(64))
 passed:Mapped[bool]=mapped_column(Boolean)
class Release(Base):
 __tablename__="qschool_releases"
 id:Mapped[str]=mapped_column(String(32),primary_key=True)
 model:Mapped[str]=mapped_column(String(32),ForeignKey("qschool_models.id"))
 environment:Mapped[str]=mapped_column(String(20))
 state:Mapped[str]=mapped_column(String(40),default="approval_requested")
 approver:Mapped[str|None]=mapped_column(String(100),nullable=True)
class Event(Base):
 __tablename__="qschool_events"
 id:Mapped[str]=mapped_column(String(32),primary_key=True)
 event:Mapped[str]=mapped_column(String(80))
 subject:Mapped[str]=mapped_column(String(32))
 info:Mapped[dict]=mapped_column(JSON)
 created:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now)

class AgentData(BaseModel):
 name:str=Field(min_length=1,max_length=100)
 operator:str=Field(min_length=1,max_length=100)
class Answers(BaseModel):
 answers:list[int]=Field(min_length=3,max_length=3)
class DatasetData(BaseModel):
 name:str=Field(min_length=1,max_length=100)
 sha256:str=Field(pattern=DIGEST)
 reference:str=Field(min_length=3,max_length=500)
 rights_confirmed:bool
class ProviderData(BaseModel):
 name:str=Field(min_length=1,max_length=100)
 category:Literal["gpu","hpc","qpu","simulator"]
class RunData(BaseModel):
 agent_id:str
 dataset_id:str
 provider_id:str
 kind:Literal["training","evaluation","quantum_experiment"]
 budget_cents:int=Field(ge=0,le=1000000)
class ResultData(BaseModel):
 status:Literal["succeeded","failed"]
 provider_job:str=Field(min_length=1,max_length=200)
 artifact_uri:str|None=Field(default=None,max_length=500)
 artifact_sha256:str|None=Field(default=None,pattern=DIGEST)
class ModelData(BaseModel):
 run_id:str
 name:str=Field(min_length=1,max_length=100)
class EvalData(BaseModel):
 metric:str=Field(min_length=1,max_length=100)
 score:float
 minimum:float
 dataset_sha256:str=Field(pattern=DIGEST)
class ReleaseData(BaseModel):
 model_id:str
 environment:Literal["sandbox","staging","production"]
class ApprovalData(BaseModel):
 approver:str=Field(min_length=2,max_length=100)

def required(db, kind, ident):
 row=db.get(kind,ident)
 if row is None: raise HTTPException(404,"Record not found")
 return row
def audit(db,event,subject,info=None):
 db.add(Event(id=new_id(),event=event,subject=subject,info=info or {}))
def completed(db,agent):
 return set(db.scalars(select(Pass.course).where(Pass.agent==agent)).all())
def create_app(database_url=None,admin_token=None):
 url=database_url or os.getenv("SCHOOL_DATABASE_URL","sqlite:///./school.db")
 key=admin_token if admin_token is not None else os.getenv("SCHOOL_ADMIN_TOKEN","")
 opts={"connect_args":{"check_same_thread":False}} if url.startswith("sqlite:") else {}
 engine=create_engine(url,pool_pre_ping=True,**opts)
 Base.metadata.create_all(engine)
 factory=sessionmaker(engine,expire_on_commit=False)
 api=FastAPI(title="Privi Quantum School",version="0.1.0",
  description="Course registry, external compute reports and deployment approval. Does not execute jobs.")
 def db_dep():
  with factory() as db: yield db
 def admin(authorization:str|None=Header(default=None)):
  if len(key)<24: raise HTTPException(503,"SCHOOL_ADMIN_TOKEN must be configured")
  supplied=authorization[7:] if authorization and authorization.startswith("Bearer ") else ""
  if not hmac.compare_digest(key,supplied): raise HTTPException(401,"Admin bearer token required")
 def course_public(cid):
  c=COURSES[cid]
  return {"id":cid,"title":c["title"],"lessons":c["lessons"],
   "questions":[{"prompt":q,"choices":choices} for q,choices,_ in c["quiz"]]}
 @api.get("/health")
 def health(db:Session=Depends(db_dep)):
  db.execute(text("SELECT 1"))
  return {"ok":True,"service":"privi-quantum-school"}
 @api.get("/courses")
 def course_list(): return {"courses":[course_public(cid) for cid in COURSES]}
 @api.post("/agents",dependencies=[Depends(admin)])
 def register(body:AgentData,db:Session=Depends(db_dep)):
  row=Agent(id=new_id(),name=body.name,operator=body.operator)
  db.add(row); audit(db,"agent.registered",row.id); db.commit()
  return {"agent_id":row.id,"required_courses":list(COURSES)}
 @api.post("/agents/{agent_id}/courses/{course_id}/assessment",dependencies=[Depends(admin)])
 def assessment(agent_id:str,course_id:str,body:Answers,db:Session=Depends(db_dep)):
  required(db,Agent,agent_id)
  if course_id not in COURSES:raise HTTPException(404,"Course not found")
  score=sum(int(answer==entry[2]) for answer,entry in zip(body.answers,COURSES[course_id]["quiz"]))
  passed=score==3
  if passed and course_id not in completed(db,agent_id):
   db.add(Pass(id=new_id(),agent=agent_id,course=course_id,score=score))
  audit(db,"course.assessed",agent_id,{"course":course_id,"score":score})
  db.commit()
  return {"passed":passed,"score":score,"knowledge_check_only":True}
 @api.get("/agents/{agent_id}/transcript",dependencies=[Depends(admin)])
 def transcript(agent_id:str,db:Session=Depends(db_dep)):
  required(db,Agent,agent_id); done=completed(db,agent_id)
  return {"completed":sorted(done),"remaining":sorted(set(COURSES)-done),"eligible":done==set(COURSES)}
 @api.post("/datasets",dependencies=[Depends(admin)])
 def datasets(body:DatasetData,db:Session=Depends(db_dep)):
  if not body.rights_confirmed:raise HTTPException(422,"Dataset rights must be documented")
  row=Dataset(id=new_id(),name=body.name,sha256=body.sha256,reference=body.reference,rights=True)
  db.add(row); audit(db,"dataset.registered",row.id,{"sha256":row.sha256}); db.commit()
  return {"dataset_id":row.id,"raw_data_uploaded":False}
 @api.post("/providers",dependencies=[Depends(admin)])
 def providers(body:ProviderData,db:Session=Depends(db_dep)):
  row=Provider(id=new_id(),name=body.name,category=body.category)
  db.add(row); audit(db,"provider.registered",row.id); db.commit()
  return {"provider_id":row.id,"status":"integration_required","hardware_connected":False}
 @api.get("/providers",dependencies=[Depends(admin)])
 def provider_list(db:Session=Depends(db_dep)):
  return {"providers":[{"id":r.id,"name":r.name,"category":r.category,"status":"integration_required"} for r in db.scalars(select(Provider)).all()]}
 @api.post("/runs",dependencies=[Depends(admin)])
 def runs(body:RunData,db:Session=Depends(db_dep)):
  required(db,Agent,body.agent_id); required(db,Dataset,body.dataset_id); required(db,Provider,body.provider_id)
  if completed(db,body.agent_id)!=set(COURSES):raise HTTPException(409,"Agent has incomplete courses")
  row=Run(id=new_id(),agent=body.agent_id,dataset=body.dataset_id,provider=body.provider_id,
          kind=body.kind,budget_cents=body.budget_cents,status="awaiting_external_executor")
  db.add(row);audit(db,"run.requested",row.id,{"budget_cents":row.budget_cents});db.commit()
  return {"run_id":row.id,"status":row.status,"execution_started":False,"payment_initiated":False}
 @api.get("/runs/{run_id}",dependencies=[Depends(admin)])
 def get_run(run_id:str,db:Session=Depends(db_dep)):
  row=required(db,Run,run_id)
  return {"run_id":row.id,"status":row.status,"kind":row.kind,"provider_job":row.provider_job,
          "artifact_sha256":row.artifact_sha256,"external_execution_verified":False}
 @api.post("/runs/{run_id}/result",dependencies=[Depends(admin)])
 def run_result(run_id:str,body:ResultData,db:Session=Depends(db_dep)):
  row=required(db,Run,run_id)
  if row.status!="awaiting_external_executor":raise HTTPException(409,"Already reported")
  if body.status=="succeeded" and (not body.artifact_uri or not body.artifact_sha256):
   raise HTTPException(422,"Successful run needs artifact reference and digest")
  row.status="reported_"+body.status;row.provider_job=body.provider_job
  row.artifact_uri=body.artifact_uri;row.artifact_sha256=body.artifact_sha256
  audit(db,"run.reported",row.id,{"status":row.status});db.commit()
  return {"status":row.status,"source":"operator_reported_not_independently_verified"}
 @api.post("/models",dependencies=[Depends(admin)])
 def model_create(body:ModelData,db:Session=Depends(db_dep)):
  run=required(db,Run,body.run_id)
  if run.kind!="training" or run.status!="reported_succeeded":
   raise HTTPException(409,"A successful externally reported training run is required")
  if db.scalar(select(Model.id).where(Model.run==run.id)):
   raise HTTPException(409,"Model exists for run")
  row=Model(id=new_id(),run=run.id,name=body.name)
  db.add(row);audit(db,"model.registered",row.id,{"artifact_sha256":run.artifact_sha256});db.commit()
  return {"model_id":row.id,"artifact_sha256":run.artifact_sha256,"weights_stored":False}
 @api.post("/models/{model_id}/evaluations",dependencies=[Depends(admin)])
 def evaluation(model_id:str,body:EvalData,db:Session=Depends(db_dep)):
  required(db,Model,model_id)
  if not (-1e12<body.score<1e12 and -1e12<body.minimum<1e12):
   raise HTTPException(422,"Metrics out of range")
  passed=body.score>=body.minimum
  row=Eval(id=new_id(),model=model_id,metric=body.metric,score=body.score,
           minimum=body.minimum,evaluation_dataset_sha256=body.dataset_sha256,passed=passed)
  db.add(row);audit(db,"evaluation.reported",model_id,{"passed":passed});db.commit()
  return {"evaluation_id":row.id,"passed":passed,"independently_verified":False}
 @api.post("/deployments",dependencies=[Depends(admin)])
 def request_release(body:ReleaseData,db:Session=Depends(db_dep)):
  model=required(db,Model,body.model_id)
  evaluations=db.scalars(select(Eval).where(Eval.model==model.id).order_by(Eval.id)).all()
  if not evaluations or not evaluations[-1].passed:
   raise HTTPException(409,"Passing evaluation required")
  run=required(db,Run,model.run)
  if completed(db,run.agent)!=set(COURSES):raise HTTPException(409,"Course prerequisites missing")
  row=Release(id=new_id(),model=model.id,environment=body.environment,state="approval_requested")
  db.add(row);audit(db,"release.requested",row.id);db.commit()
  return {"deployment_id":row.id,"state":row.state,"deployed":False}
 @api.post("/deployments/{deploy_id}/approve",dependencies=[Depends(admin)])
 def approval(deploy_id:str,body:ApprovalData,db:Session=Depends(db_dep)):
  row=required(db,Release,deploy_id)
  if row.state!="approval_requested":raise HTTPException(409,"Already acted upon")
  if row.environment=="production" and os.getenv("SCHOOL_ALLOW_PRODUCTION_APPROVAL")!="1":
   raise HTTPException(403,"Production approval disabled by default")
  row.state="approved_not_deployed";row.approver=body.approver
  audit(db,"release.approved",row.id,{"approver":body.approver});db.commit()
  return {"state":row.state,"deployed":False,"next":"Connect independently tested worker"}
 @api.get("/events",dependencies=[Depends(admin)])
 def events(db:Session=Depends(db_dep)):
  entries=db.scalars(select(Event).order_by(Event.created.desc()).limit(100)).all()
  return {"events":[{"event":x.event,"subject":x.subject,"info":x.info} for x in entries],
          "signed":False,"note":"Operational event log, not Privi Ledger attestation"}
 return api

app=create_app()
