import os
from typing import List, Optional
from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Request, Header, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from bson import ObjectId, Regex
import re
import csv
import io
from datetime import datetime, date

from database import db, create_document, get_documents
from schemas import Landlord, Property, WorkOrder, Certificate, ActivityLog, TenantIssue, LinkToken, User, Location

app = FastAPI(title="Property Asset Management API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve uploaded files
UPLOAD_DIR = os.path.join(os.getcwd(), 'uploads')
CERT_DIR = os.path.join(UPLOAD_DIR, 'certificates')
ISSUE_DIR = os.path.join(UPLOAD_DIR, 'issues')
os.makedirs(CERT_DIR, exist_ok=True)
os.makedirs(ISSUE_DIR, exist_ok=True)
app.mount("/files", StaticFiles(directory=UPLOAD_DIR), name="files")

# Helpers
class IdModel(BaseModel):
    id: str

def ensure_object_id(id_str: str) -> ObjectId:
    try:
        return ObjectId(id_str)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid id format")

def log_action(action: str, entity: str, entity_id: Optional[str] = None, actor: Optional[str] = None, role: Optional[str] = None, details: Optional[str] = None):
    try:
        payload = ActivityLog(action=action, entity=entity, entity_id=entity_id, actor=actor, role=role, details=details)
        create_document('activitylog', payload)
    except Exception:
        pass

# Admin auth helper
ADMIN_HEADER = "X-Admin-Token"

def get_admin_token() -> str:
    return os.getenv("ADMIN_TOKEN", "secret-admin-token")

def is_admin(request: Request, token_query: Optional[str]) -> bool:
    header_token = request.headers.get(ADMIN_HEADER)
    admin_token = get_admin_token()
    return (token_query is not None and token_query == admin_token) or (header_token is not None and header_token == admin_token)

# Operative auth helpers
OPERATIVE_HEADER = "X-Operative-Token"

def create_user_token() -> str:
    return os.urandom(16).hex()

async def get_current_operative(operative_token: Optional[str] = Header(None, alias=OPERATIVE_HEADER)):
    if not operative_token:
        raise HTTPException(status_code=401, detail="Missing operative token")
    user = db['user'].find_one({"auth_token": operative_token, "role": "operative"})
    if not user:
        raise HTTPException(status_code=401, detail="Invalid operative token")
    user['id'] = str(user.pop('_id'))
    return user

@app.get("/")
def read_root():
    return {"message": "Property Asset Management API is running"}


@app.get("/test")
def test_database():
    response = {
        "backend": "✅ Running",
        "database": "❌ Not Available",
        "database_url": None,
        "database_name": None,
        "connection_status": "Not Connected",
        "collections": []
    }
    try:
        if db is not None:
            response["database"] = "✅ Available"
            response["database_url"] = "✅ Set" if os.getenv("DATABASE_URL") else "❌ Not Set"
            response["database_name"] = db.name
            response["connection_status"] = "Connected"
            try:
                collections = db.list_collection_names()
                response["collections"] = collections[:10]
                response["database"] = "✅ Connected & Working"
            except Exception as e:
                response["database"] = f"⚠️  Connected but Error: {str(e)[:80]}"
        else:
            response["database"] = "⚠️  Available but not initialized"
    except Exception as e:
        response["database"] = f"❌ Error: {str(e)[:80]}"
    return response

# Landlords
@app.get("/api/landlords")
def list_landlords(limit: int = 50):
    docs = get_documents("landlord", {}, limit)
    for d in docs:
        d["id"] = str(d.pop("_id"))
    return docs


@app.post("/api/landlords")
def create_landlord(payload: Landlord):
    inserted_id = create_document("landlord", payload)
    log_action("create_landlord", "landlord", inserted_id)
    return {"id": inserted_id}

# Properties
@app.get("/api/properties")
def list_properties(landlord_id: Optional[str] = None, limit: int = 50):
    filt = {}
    if landlord_id:
        filt["landlord_id"] = landlord_id
    docs = get_documents("property", filt, limit)
    for d in docs:
        d["id"] = str(d.pop("_id"))
    return docs

@app.get("/api/properties/{property_id}")
def get_property_detail(property_id: str):
    prop = db['property'].find_one({"_id": ensure_object_id(property_id)})
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")
    prop["id"] = str(prop.pop("_id"))
    works = list(db['workorder'].find({"property_id": property_id}).sort("created_at", -1))
    for w in works:
        w["id"] = str(w.pop("_id"))
    certs = list(db['certificate'].find({"property_id": property_id}).sort("created_at", -1))
    for c in certs:
        c["id"] = str(c.pop("_id"))
    # upcoming renewals
    upcoming = []
    today = date.today()
    for c in certs:
        exp = c.get('expiry_date')
        if isinstance(exp, datetime):
            exp_d = exp.date()
        else:
            exp_d = exp
        if exp_d:
            delta = (exp_d - today).days
            if delta <= 60:
                upcoming.append({"type": c.get('type'), "expiry_date": exp_d.isoformat(), "days": delta})
    issues = list(db['tenantissue'].find({"property_id": property_id}).sort("created_at", -1))
    for i in issues:
        i["id"] = str(i.pop("_id"))
    return {"property": prop, "workorders": works, "certificates": certs, "upcoming": upcoming, "issues": issues}

@app.post("/api/properties")
def create_property(payload: Property):
    inserted_id = create_document("property", payload)
    log_action("create_property", "property", inserted_id)
    return {"id": inserted_id}

# Property search/validation
@app.get("/api/properties/search")
def search_properties(query: str, limit: int = 10):
    if not query or len(query.strip()) < 2:
        raise HTTPException(status_code=400, detail="Query too short")
    q = query.strip()
    regex = {"$regex": q, "$options": "i"}
    filt = {"$or": [
        {"address_line1": regex},
        {"address_line2": regex},
        {"city": regex},
        {"postcode": regex}
    ]}
    docs = list(db['property'].find(filt).limit(limit))
    results = []
    for d in docs:
        d_id = str(d.get('_id'))
        addr = f"{d.get('address_line1','')}, {d.get('city','')} {d.get('postcode','')}".strip()
        results.append({"id": d_id, "address": addr})
    return {"results": results}

@app.get("/api/properties/validate")
def validate_property(address: str):
    q = address.strip()
    if not q:
        return {"valid": False, "matches": []}
    regex = {"$regex": q, "$options": "i"}
    filt = {"$or": [
        {"address_line1": regex},
        {"address_line2": regex},
        {"city": regex},
        {"postcode": regex}
    ]}
    docs = list(db['property'].find(filt).limit(5))
    matches = []
    for d in docs:
        matches.append({
            "id": str(d.get('_id')),
            "address": f"{d.get('address_line1','')}, {d.get('city','')} {d.get('postcode','')}".strip()
        })
    return {"valid": len(matches) > 0, "matches": matches}

# Work Orders
@app.get("/api/workorders")
def list_workorders(property_id: Optional[str] = None, status: Optional[str] = None, operative_id: Optional[str] = None, limit: int = 50):
    filt = {}
    if property_id:
        filt["property_id"] = property_id
    if status:
        filt["status"] = status
    if operative_id:
        filt["operative_id"] = operative_id
    docs = get_documents("workorder", filt, limit)
    for d in docs:
        d["id"] = str(d.pop("_id"))
    return docs

@app.post("/api/workorders")
def create_workorder(payload: WorkOrder):
    # Validate property exists before creating a work order
    prop = db['property'].find_one({"_id": ensure_object_id(payload.property_id)}) if payload.property_id else None
    if not prop:
        raise HTTPException(status_code=400, detail="Unknown property. This may not be a managed property.")
    inserted_id = create_document("workorder", payload)
    log_action("create_workorder", "workorder", inserted_id)
    return {"id": inserted_id}

# Operative auth & job lifecycle
class OperativeLogin(BaseModel):
    email: str

@app.post("/api/operative/login")
def operative_login(payload: OperativeLogin):
    # find or create operative user and issue token
    found = db['user'].find_one({"email": payload.email})
    token = create_user_token()
    if found:
        db['user'].update_one({"_id": found['_id']}, {"$set": {"role": "operative", "auth_token": token}})
        user = db['user'].find_one({"_id": found['_id']})
    else:
        user_doc = User(email=payload.email, role='operative', auth_token=token)
        inserted_id = create_document('user', user_doc)
        user = db['user'].find_one({"_id": ensure_object_id(inserted_id)})
    log_action('operative_login', 'user', str(user['_id']), actor=payload.email, role='operative')
    return {"token": token, "operative_id": str(user.get('_id')), "email": user.get('email')}

class JobStart(BaseModel):
    workorder_id: str
    location: Optional[Location] = None

@app.post("/api/operative/start")
def start_job(payload: JobStart, user=Depends(get_current_operative)):
    # set in_progress and timestamp/location
    now = datetime.utcnow()
    update = {
        "$set": {
            "status": "in_progress",
            "started_at": now,
            "operative_id": user['id']
        }
    }
    if payload.location:
        update["$set"]["started_location"] = payload.location.dict()
    res = db['workorder'].update_one({"_id": ensure_object_id(payload.workorder_id)}, update)
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Work order not found")
    log_action('operative_start', 'workorder', payload.workorder_id, actor=user.get('email'), role='operative')
    return {"ok": True}

class JobComplete(BaseModel):
    workorder_id: str
    location: Optional[Location] = None
    notes: Optional[str] = None

@app.post("/api/operative/complete")
def complete_job(payload: JobComplete, user=Depends(get_current_operative)):
    now = datetime.utcnow()
    update = {
        "$set": {
            "status": "completed",
            "completed_at": now
        }
    }
    if payload.location:
        update["$set"]["completed_location"] = payload.location.dict()
    if payload.notes:
        update["$set"]["description"] = payload.notes
    res = db['workorder'].update_one({"_id": ensure_object_id(payload.workorder_id)}, update)
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Work order not found")
    log_action('operative_complete', 'workorder', payload.workorder_id, actor=user.get('email'), role='operative')
    return {"ok": True}

# Certificates
@app.get("/api/certificates")
def list_certificates(property_id: Optional[str] = None, ctype: Optional[str] = None, limit: int = 50):
    filt = {}
    if property_id:
        filt["property_id"] = property_id
    if ctype:
        filt["type"] = ctype
    docs = get_documents("certificate", filt, limit)
    for d in docs:
        d["id"] = str(d.pop("_id"))
    return docs

@app.get("/api/certificates/expiring")
def list_expiring_certificates(days: int = 60):
    today = date.today()
    docs = get_documents("certificate", {}, 1000)
    expiring = []
    for d in docs:
        d["id"] = str(d.pop("_id"))
        exp = d.get('expiry_date')
        exp_date = exp.date() if isinstance(exp, datetime) else exp
        if exp_date:
            delta = (exp_date - today).days
            if delta <= days:
                d['days_to_expiry'] = delta
                expiring.append(d)
    expiring.sort(key=lambda x: x.get('days_to_expiry', 9999))
    return expiring

@app.post("/api/certificates")
def create_certificate(payload: Certificate):
    inserted_id = create_document("certificate", payload)
    log_action("create_certificate", "certificate", inserted_id)
    return {"id": inserted_id}

@app.post("/api/certificates/upload")
async def upload_certificate(
    property_id: str = Form(...),
    type: str = Form(...),
    certificate_number: Optional[str] = Form(None),
    issue_date: Optional[str] = Form(None),
    expiry_date: Optional[str] = Form(None),
    uploaded_by: Optional[str] = Form(None),
    notes: Optional[str] = Form(None),
    file: UploadFile = File(...)
):
    safe_name = f"{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{file.filename}"
    dest_path = os.path.join(CERT_DIR, safe_name)
    with open(dest_path, 'wb') as f:
        content = await file.read()
        f.write(content)
    cert = {
        "property_id": property_id,
        "type": type,
        "certificate_number": certificate_number,
        "uploaded_by": uploaded_by,
        "notes": notes,
        "file_path": f"/files/certificates/{safe_name}",
        "file_name": file.filename
    }
    try:
        if issue_date:
            cert['issue_date'] = date.fromisoformat(issue_date)
        if expiry_date:
            cert['expiry_date'] = date.fromisoformat(expiry_date)
    except Exception:
        pass
    inserted_id = create_document('certificate', cert)
    log_action("upload_certificate", "certificate", inserted_id)
    return {"id": inserted_id, "file_url": cert['file_path']}

# CSV import/export and reports
@app.post("/api/landlords/import_csv")
async def import_landlords_csv(file: UploadFile = File(...)):
    if not file.filename.lower().endswith('.csv'):
        raise HTTPException(status_code=400, detail="Please upload a CSV file")
    content = await file.read()
    text = content.decode('utf-8')
    reader = csv.DictReader(io.StringIO(text))
    inserted = 0
    for row in reader:
        payload = Landlord(
            name=row.get('name') or row.get('Name') or '',
            email=row.get('email') or row.get('Email'),
            phone=row.get('phone') or row.get('Phone'),
            address=row.get('address') or row.get('Address'),
            notes=row.get('notes') or row.get('Notes')
        )
        if payload.name:
            create_document('landlord', payload)
            inserted += 1
    log_action("import_landlords_csv", "landlord", details=f"inserted={inserted}")
    return {"inserted": inserted}

@app.get("/api/reports/summary")
def summary_report():
    landlords = list(db['landlord'].find())
    properties = list(db['property'].find())
    works = list(db['workorder'].find())
    certs = list(db['certificate'].find())
    summary = {
        "landlords": len(landlords),
        "properties": len(properties),
        "workorders": len(works),
        "certificates": len(certs)
    }
    return summary

@app.get("/api/reports/landlords.csv")
def landlords_csv():
    landlords = list(db['landlord'].find())
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["id","name","email","phone","address","notes"])
    for l in landlords:
        writer.writerow([str(l.get('_id')), l.get('name',''), l.get('email',''), l.get('phone',''), l.get('address',''), l.get('notes','')])
    output.seek(0)
    return StreamingResponse(iter([output.getvalue()]), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=landlords.csv"})

@app.get("/api/reports/rent-statement")
def rent_statement(landlord_id: str, month: str):
    try:
        start = datetime.strptime(month + "-01", "%Y-%m-%d").date()
        if start.month == 12:
            end = date(start.year + 1, 1, 1)
        else:
            end = date(start.year, start.month + 1, 1)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid month format; use YYYY-MM")

    props = list(db['property'].find({"landlord_id": landlord_id}))
    prop_ids = [str(p.get('_id')) for p in props]
    rent_total = sum([p.get('rent_amount') or 0 for p in props])

    works = list(db['workorder'].find({
        "property_id": {"$in": prop_ids},
        "status": "completed",
        "scheduled_for": {"$gte": start, "$lt": end}
    }))
    deductions = sum([w.get('cost') or 0 for w in works])

    statement = {
        "landlord_id": landlord_id,
        "month": month,
        "properties": [{"id": str(p.get('_id')), "address": f"{p.get('address_line1','')}, {p.get('city','')} {p.get('postcode','')}", "rent": p.get('rent_amount') or 0} for p in props],
        "workorders": [{"id": str(w.get('_id')), "property_id": w.get('property_id'), "title": w.get('title'), "cost": w.get('cost') or 0} for w in works],
        "rent_total": rent_total,
        "deductions": deductions,
        "net": rent_total - deductions
    }
    return statement

# Activity
@app.get("/api/activity")
def list_activity(limit: int = 50):
    logs = get_documents('activitylog', {}, limit)
    for a in logs:
        a['id'] = str(a.pop('_id'))
    return logs

# Tenant link + reporting
@app.post("/api/tenant/link")
def create_tenant_link(property_id: str):
    token = os.urandom(16).hex()
    doc = LinkToken(token=token, property_id=property_id)
    create_document('linktoken', doc)
    return {"token": token}

@app.post("/api/tenant/report")
async def tenant_report(
    token: str = Form(...),
    description: str = Form(...),
    tenant_name: Optional[str] = Form(None),
    tenant_contact: Optional[str] = Form(None),
    priority: Optional[str] = Form('medium'),
    photo: UploadFile | None = File(None)
):
    tok = db['linktoken'].find_one({"token": token})
    if not tok:
        raise HTTPException(status_code=400, detail="Invalid link token")
    property_id = tok.get('property_id')

    photos = []
    if photo:
        safe_name = f"issue_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{photo.filename}"
        dest = os.path.join(ISSUE_DIR, safe_name)
        with open(dest, 'wb') as f:
            content = await photo.read()
            f.write(content)
        photos.append(f"/files/issues/{safe_name}")

    issue = TenantIssue(property_id=property_id, tenant_name=tenant_name, tenant_contact=tenant_contact, description=description, priority=priority, photos=photos)
    issue_id = create_document('tenantissue', issue)
    log_action('tenant_report', 'tenantissue', issue_id)
    return {"id": issue_id}

# Tenant: send email on behalf (activity log placeholder)
class TenantEmail(BaseModel):
    intent: str
    name: Optional[str] = None
    contact: Optional[str] = None
    address: Optional[str] = None
    details: Optional[str] = None
    priority: Optional[str] = None

@app.post("/api/tenant/send_email")
def tenant_send_email(payload: TenantEmail):
    # validate managed property when address provided
    if payload.address:
        regex = {"$regex": payload.address.strip(), "$options": "i"}
        filt = {"$or": [
            {"address_line1": regex},
            {"address_line2": regex},
            {"city": regex},
            {"postcode": regex}
        ]}
        prop = db['property'].find_one(filt)
        if not prop:
            raise HTTPException(status_code=400, detail="We couldn't find this address in our system. It may not be a managed property.")
    # log as email activity (placeholder for real email service)
    summary = {
        "intent": payload.intent,
        "name": payload.name,
        "contact": payload.contact,
        "address": payload.address,
        "details": payload.details,
        "priority": payload.priority,
    }
    log_action('tenant_send_email', 'tenant', details=str(summary))
    return {"ok": True}

# Operative: upload repair photos and add works
@app.post("/api/operative/work")
async def operative_add_work(
    property_id: str = Form(...),
    title: str = Form(...),
    description: Optional[str] = Form(None),
    category: Optional[str] = Form('repair'),
    cost: Optional[float] = Form(None),
    photo: UploadFile | None = File(None)
):
    photos = []
    if photo:
        safe_name = f"work_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{photo.filename}"
        dest = os.path.join(ISSUE_DIR, safe_name)
        with open(dest, 'wb') as f:
            content = await photo.read()
            f.write(content)
        photos.append(f"/files/issues/{safe_name}")
    wo = WorkOrder(property_id=property_id, title=title, description=description, category=category, status='in_progress', cost=None, photos=photos)
    wo_id = create_document('workorder', wo)
    log_action('operative_add_work', 'workorder', wo_id)
    return {"id": wo_id}

# Admin Quick Add (HTML form)
@app.get("/admin/quick-add", response_class=HTMLResponse)
async def admin_quick_add_form(request: Request, token: Optional[str] = None):
    if not is_admin(request, token):
        return HTMLResponse("<h1>Unauthorized</h1><p>Missing or invalid admin token.</p>", status_code=401)
    html = f"""
    <!doctype html>
    <html lang=\"en\">\n    <head>
      <meta charset=\"utf-8\" />
      <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
      <title>Admin Quick Add</title>
      <style>
        body {{ font-family: system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial, sans-serif; padding: 24px; color: #0f172a; }}
        .card {{ max-width: 720px; margin: 0 auto; border: 1px solid #e2e8f0; border-radius: 12px; padding: 20px; box-shadow: 0 4px 14px rgba(0,0,0,0.06); }}
        label {{ display: block; margin-top: 12px; font-weight: 600; }}
        input, select, textarea {{ width: 100%; padding: 10px 12px; border: 1px solid #cbd5e1; border-radius: 8px; margin-top: 6px; }}
        textarea {{ min-height: 100px; }}
        .row {{ display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }}
        button {{ margin-top: 16px; background: #0ea5e9; color: white; border: 0; padding: 10px 14px; border-radius: 10px; cursor: pointer; }}
        .muted {{ color: #64748b; font-size: 14px; }}
      </style>
    </head>
    <body>
      <div class=\"card\">\n        <h1>Admin Quick Add</h1>
        <p class=\"muted\">Create a quick Work Order or Tenant Issue. Uploading a photo is optional.</p>
        <form method=\"post\" action=\"/admin/quick-add?token={token or ''}\" enctype=\"multipart/form-data\">\n          <label>Type
            <select name=\"type\">\n              <option value=\"workorder\">Work Order</option>
              <option value=\"issue\">Tenant Issue</option>
            </select>
          </label>
          <div class=\"row\">\n            <div>
              <label>Property ID
                <input name=\"property_id\" placeholder=\"e.g. 65f...\" required />
              </label>
            </div>
            <div>
              <label>Priority (for Issues)
                <select name=\"priority\">\n                  <option value=\"low\">Low</option>
                  <option value=\"medium\" selected>Medium</option>
                  <option value=\"high\">High</option>
                </select>
              </label>
            </div>
          </div>
          <label>Title
            <input name=\"title\" placeholder=\"Short title\" />
          </label>
          <label>Description
            <textarea name=\"description\" placeholder=\"Describe the work or issue...\"></textarea>
          </label>
          <label>Photo (optional)
            <input type=\"file\" name=\"photo\" accept=\"image/*\" />
          </label>
          <button type=\"submit\">Create</button>
        </form>
        <p class=\"muted\" style=\"margin-top:12px\">Auth: pass token via URL (?token=...) or header X-Admin-Token</p>
      </div>
    </body>
    </html>
    """
    return HTMLResponse(html)

@app.post("/admin/quick-add", response_class=HTMLResponse)
async def admin_quick_add_submit(
    request: Request,
    token: Optional[str] = None,
    type: str = Form('workorder'),
    property_id: str = Form(...),
    title: Optional[str] = Form(None),
    description: Optional[str] = Form(None),
    priority: Optional[str] = Form('medium'),
    photo: UploadFile | None = File(None)
):
    if not is_admin(request, token):
        return HTMLResponse("<h1>Unauthorized</h1><p>Missing or invalid admin token.</p>", status_code=401)

    created_id = None
    file_url = None

    photos = []
    if photo:
        safe_name = f"admin_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{photo.filename}"
        dest = os.path.join(ISSUE_DIR, safe_name)
        with open(dest, 'wb') as f:
            content = await photo.read()
            f.write(content)
        file_url = f"/files/issues/{safe_name}"
        photos.append(file_url)

    if type == 'issue':
        issue = TenantIssue(property_id=property_id, tenant_name=None, tenant_contact=None, description=description or (title or ''), priority=priority, photos=photos)
        created_id = create_document('tenantissue', issue)
        log_action('admin_quick_add_issue', 'tenantissue', created_id, actor='admin', role='admin')
    else:
        # default to workorder
        # validate property
        prop = db['property'].find_one({"_id": ensure_object_id(property_id)})
        if not prop:
            return HTMLResponse("<h1>Error</h1><p>Unknown property. Not a managed property.</p>", status_code=400)
        wo = WorkOrder(property_id=property_id, title=title or 'Quick Work Order', description=description, category='maintenance', status='new', cost=None, photos=photos)
        created_id = create_document('workorder', wo)
        log_action('admin_quick_add_workorder', 'workorder', created_id, actor='admin', role='admin')

    html = f"""
    <!doctype html>
    <html lang=\"en\">\n<head><meta charset=\"utf-8\" /><meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" /><title>Created</title>
    <style>body {{ font-family: system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial, sans-serif; padding: 24px; color: #0f172a; }}</style></head>
    <body>
      <h1>Created successfully</h1>
      <p>ID: {created_id}</p>
      {f"<p>Photo: <a href='{file_url}' target='_blank'>{file_url}</a></p>" if file_url else ""}
      <p><a href=\"/admin/quick-add?token={token or ''}\">Create another</a></p>
    </body>
    </html>
    """
    return HTMLResponse(html)

# Admin: Seed a work order for an operative by email and property address
class SeedWorkOrderPayload(BaseModel):
    operative_email: str
    address: str
    title: Optional[str] = "Test job"
    description: Optional[str] = "Seeded job for testing"
    category: Optional[str] = "maintenance"

@app.post("/api/admin/seed_workorder_for_operative")
def seed_workorder_for_operative(payload: SeedWorkOrderPayload, request: Request, token: Optional[str] = None):
    if not is_admin(request, token):
        raise HTTPException(status_code=401, detail="Unauthorized")
    # find property by address
    q = payload.address.strip()
    regex = {"$regex": q, "$options": "i"}
    filt = {"$or": [
        {"address_line1": regex},
        {"address_line2": regex},
        {"city": regex},
        {"postcode": regex}
    ]}
    prop = db['property'].find_one(filt)
    if not prop:
        raise HTTPException(status_code=400, detail="No matching property found. Not a managed property.")
    property_id = str(prop.get('_id'))
    # ensure operative user exists and get id
    existing = db['user'].find_one({"email": payload.operative_email})
    if existing:
        operative_id = str(existing.get('_id'))
        # ensure role operative
        db['user'].update_one({"_id": existing.get('_id')}, {"$set": {"role": "operative"}})
    else:
        user_doc = User(email=payload.operative_email, role='operative', auth_token=create_user_token())
        inserted_id = create_document('user', user_doc)
        operative_id = inserted_id
    # create workorder assigned
    wo = WorkOrder(property_id=property_id, title=payload.title, description=payload.description, category=payload.category, status='new', cost=None, photos=[])
    wo_id = create_document('workorder', wo)
    db['workorder'].update_one({"_id": ensure_object_id(wo_id)}, {"$set": {"operative_id": operative_id}})
    log_action('seed_workorder_for_operative', 'workorder', wo_id, actor='admin', role='admin', details=f"operative={payload.operative_email}")
    return {"id": wo_id, "property_id": property_id, "operative_id": operative_id}

# Dev: tokenless seed for testing environments
class DevSeedPayload(BaseModel):
    operative_email: str
    address: str
    title: Optional[str] = "Test job"
    description: Optional[str] = "Seeded job for testing"
    category: Optional[str] = "maintenance"

@app.post("/api/dev/seed")
def dev_seed(payload: DevSeedPayload):
    if os.getenv("ALLOW_DEV_SEED", "1") != "1":
        raise HTTPException(status_code=403, detail="Dev seeding disabled")
    # find property by address; if missing, create a minimal property
    q = payload.address.strip()
    regex = {"$regex": q, "$options": "i"}
    filt = {"$or": [
        {"address_line1": regex},
        {"address_line2": regex},
        {"city": regex},
        {"postcode": regex}
    ]}
    prop = db['property'].find_one(filt)
    if not prop:
        # create minimal property
        new_prop = Property(
            landlord_id=None,
            address_line1=payload.address,
            address_line2=None,
            city="",
            postcode="",
            rent_amount=None,
            notes="Auto-created via dev seed"
        )
        property_id = create_document('property', new_prop)
    else:
        property_id = str(prop.get('_id'))
    # ensure operative exists
    existing = db['user'].find_one({"email": payload.operative_email})
    if existing:
        operative_id = str(existing.get('_id'))
        db['user'].update_one({"_id": existing.get('_id')}, {"$set": {"role": "operative"}})
    else:
        user_doc = User(email=payload.operative_email, role='operative', auth_token=create_user_token())
        operative_id = create_document('user', user_doc)
    # create and assign workorder
    wo = WorkOrder(property_id=property_id, title=payload.title, description=payload.description, category=payload.category, status='new', cost=None, photos=[])
    wo_id = create_document('workorder', wo)
    db['workorder'].update_one({"_id": ensure_object_id(wo_id)}, {"$set": {"operative_id": operative_id}})
    log_action('dev_seed_workorder', 'workorder', wo_id, actor='dev', role='dev', details=f"operative={payload.operative_email}")
    return {"id": wo_id, "property_id": property_id, "operative_id": operative_id}

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
