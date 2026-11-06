from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_, func
from sqlalchemy.orm import Session, joinedload
from app.database import get_db
from app.models import Provider, Branch, SourceObservation, AuditEvent
from app.schemas import ProviderCreate, ProviderUpdate, ProviderOut, BranchInput, BranchOut, ObservationCreate, ObservationDecision

router = APIRouter(prefix="/api/v1", tags=["directory"])
ALLOWED_PROVIDER_STATUSES = {"draft", "needs_review", "approved", "published", "suspended", "rejected"}
ALLOWED_BRANCH_STATUSES = {"draft", "published", "suspended"}

def audit(db, entity_type, entity_id, action, detail=None):
    db.add(AuditEvent(entity_type=entity_type, entity_id=entity_id, action=action, detail=detail or {}))

def provider_dict(p):
    return {"id":p.id,"trading_name":p.trading_name,"registered_name":p.registered_name,"website":p.website,"provider_type":p.provider_type,"status":p.status,"verification_status":p.verification_status,"notes":p.notes,"created_at":p.created_at,"updated_at":p.updated_at,"branches":[branch_dict(b) for b in p.branches]}

def branch_dict(b):
    return {"id":b.id,"provider_id":b.provider_id,"branch_name":b.branch_name,"address_line_1":b.address_line_1,"address_line_2":b.address_line_2,"town_city":b.town_city,"county":b.county,"postcode":b.postcode,"telephone":b.telephone,"email":b.email,"website":b.website,"latitude":b.latitude,"longitude":b.longitude,"services":b.services or [],"status":b.status}

@router.get("/dashboard")
def dashboard(db: Session = Depends(get_db)):
    return {"providers":db.query(Provider).count(),"branches":db.query(Branch).count(),"published":db.query(Provider).filter(Provider.status=="published").count(),"needs_review":db.query(Provider).filter(Provider.status=="needs_review").count(),"draft":db.query(Provider).filter(Provider.status=="draft").count(),"observations_pending":db.query(SourceObservation).filter(SourceObservation.review_status=="pending").count()}

@router.get("/providers")
def list_providers(q: str | None = None, status: str | None = None, limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0), db: Session = Depends(get_db)):
    query = db.query(Provider).options(joinedload(Provider.branches))
    if q:
        like=f"%{q.strip()}%"
        query=query.outerjoin(Branch).filter(or_(Provider.trading_name.ilike(like), Provider.registered_name.ilike(like), Branch.branch_name.ilike(like), Branch.town_city.ilike(like), Branch.postcode.ilike(like))).distinct()
    if status: query=query.filter(Provider.status==status)
    rows=query.order_by(Provider.trading_name).offset(offset).limit(limit).all()
    return {"items":[provider_dict(p) for p in rows],"count":query.count()}

@router.post("/providers", status_code=201)
def create_provider(payload: ProviderCreate, db: Session = Depends(get_db)):
    p=Provider(trading_name=payload.trading_name.strip(),registered_name=payload.registered_name,website=payload.website,provider_type=payload.provider_type,notes=payload.notes)
    for item in payload.branches: p.branches.append(Branch(**item.model_dump()))
    db.add(p); db.flush(); audit(db,"provider",p.id,"created",{"trading_name":p.trading_name,"branch_count":len(p.branches)}); db.commit(); db.refresh(p)
    return provider_dict(p)

@router.get("/providers/{provider_id}")
def get_provider(provider_id: int, db: Session = Depends(get_db)):
    p=db.query(Provider).options(joinedload(Provider.branches)).filter(Provider.id==provider_id).first()
    if not p: raise HTTPException(404,"Provider not found")
    return provider_dict(p)

@router.patch("/providers/{provider_id}")
def update_provider(provider_id: int, payload: ProviderUpdate, db: Session = Depends(get_db)):
    p=db.get(Provider,provider_id)
    if not p: raise HTTPException(404,"Provider not found")
    changes=payload.model_dump(exclude_unset=True)
    for k,v in changes.items(): setattr(p,k,v)
    audit(db,"provider",p.id,"updated",changes); db.commit(); db.refresh(p)
    return provider_dict(p)

@router.post("/providers/{provider_id}/branches", status_code=201)
def add_branch(provider_id: int, payload: BranchInput, db: Session = Depends(get_db)):
    p=db.get(Provider,provider_id)
    if not p: raise HTTPException(404,"Provider not found")
    b=Branch(provider_id=provider_id,**payload.model_dump()); db.add(b); db.flush(); audit(db,"branch",b.id,"created",{"provider_id":provider_id}); db.commit(); db.refresh(b)
    return branch_dict(b)

@router.patch("/providers/{provider_id}/status")
def set_provider_status(provider_id: int, status: str, db: Session = Depends(get_db)):
    if status not in ALLOWED_PROVIDER_STATUSES: raise HTTPException(400,"Invalid provider status")
    p=db.get(Provider,provider_id)
    if not p: raise HTTPException(404,"Provider not found")
    p.status=status
    if status=="published":
        p.verification_status="approved"
        for branch in p.branches:
            if branch.status == "draft": branch.status = "published"
    audit(db,"provider",p.id,"status_changed",{"status":status}); db.commit(); return {"id":p.id,"status":p.status}

@router.post("/observations", status_code=201)
def create_observation(payload: ObservationCreate, db: Session = Depends(get_db)):
    if payload.provider_id and not db.get(Provider,payload.provider_id): raise HTTPException(404,"Provider not found")
    if payload.branch_id and not db.get(Branch,payload.branch_id): raise HTTPException(404,"Branch not found")
    o=SourceObservation(**payload.model_dump()); db.add(o); db.flush(); audit(db,"observation",o.id,"captured",{"source_name":o.source_name}); db.commit(); db.refresh(o)
    return observation_dict(o)

def observation_dict(o):
    return {"id":o.id,"provider_id":o.provider_id,"branch_id":o.branch_id,"source_type":o.source_type,"source_name":o.source_name,"source_url":o.source_url,"retrieved_at":o.retrieved_at,"confidence":o.confidence,"observed_data":o.observed_data,"review_status":o.review_status,"notes":o.notes}

@router.get("/observations")
def list_observations(review_status: str | None = None, db: Session = Depends(get_db)):
    q=db.query(SourceObservation)
    if review_status: q=q.filter(SourceObservation.review_status==review_status)
    return {"items":[observation_dict(o) for o in q.order_by(SourceObservation.retrieved_at.desc()).limit(200).all()]}

@router.patch("/observations/{observation_id}")
def decide_observation(observation_id: int, payload: ObservationDecision, db: Session = Depends(get_db)):
    if payload.review_status not in {"accepted","rejected","pending"}: raise HTTPException(400,"Invalid review status")
    o=db.get(SourceObservation,observation_id)
    if not o: raise HTTPException(404,"Observation not found")
    o.review_status=payload.review_status; o.notes=payload.notes or o.notes
    audit(db,"observation",o.id,"reviewed",{"review_status":o.review_status}); db.commit(); return observation_dict(o)

@router.get("/directory/search")
def public_search(q: str = Query(min_length=2), limit: int = Query(50,ge=1,le=100), db: Session = Depends(get_db)):
    like=f"%{q.strip()}%"
    rows=(db.query(Branch,Provider).join(Provider).filter(Provider.status=="published",Branch.status=="published").filter(or_(Provider.trading_name.ilike(like),Branch.branch_name.ilike(like),Branch.town_city.ilike(like),Branch.postcode.ilike(like))).order_by(Branch.town_city,Provider.trading_name).limit(limit).all())
    return {"items":[{"provider_name":p.trading_name,"provider_id":p.id,**branch_dict(b)} for b,p in rows],"count":len(rows)}
