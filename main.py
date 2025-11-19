import os
from typing import List, Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from bson import ObjectId

from database import db, create_document, get_documents
from schemas import Landlord, Property, WorkOrder, Certificate

app = FastAPI(title="Property Asset Management API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Helpers
class IdModel(BaseModel):
    id: str


def ensure_object_id(id_str: str) -> ObjectId:
    try:
        return ObjectId(id_str)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid id format")


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


# Generic list endpoints for each schema
@app.get("/api/landlords")
def list_landlords(limit: int = 50):
    docs = get_documents("landlord", {}, limit)
    for d in docs:
        d["id"] = str(d.pop("_id"))
    return docs


@app.post("/api/landlords")
def create_landlord(payload: Landlord):
    inserted_id = create_document("landlord", payload)
    return {"id": inserted_id}


@app.get("/api/properties")
def list_properties(landlord_id: Optional[str] = None, limit: int = 50):
    filt = {}
    if landlord_id:
        try:
            filt["landlord_id"] = landlord_id
        except Exception:
            pass
    docs = get_documents("property", filt, limit)
    for d in docs:
        d["id"] = str(d.pop("_id"))
    return docs


@app.post("/api/properties")
def create_property(payload: Property):
    inserted_id = create_document("property", payload)
    return {"id": inserted_id}


@app.get("/api/workorders")
def list_workorders(property_id: Optional[str] = None, status: Optional[str] = None, limit: int = 50):
    filt = {}
    if property_id:
        filt["property_id"] = property_id
    if status:
        filt["status"] = status
    docs = get_documents("workorder", filt, limit)
    for d in docs:
        d["id"] = str(d.pop("_id"))
    return docs


@app.post("/api/workorders")
def create_workorder(payload: WorkOrder):
    inserted_id = create_document("workorder", payload)
    return {"id": inserted_id}


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


@app.post("/api/certificates")
def create_certificate(payload: Certificate):
    inserted_id = create_document("certificate", payload)
    return {"id": inserted_id}


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
