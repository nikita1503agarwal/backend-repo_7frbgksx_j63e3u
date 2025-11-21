"""
Database Schemas for Property Asset Management

Each Pydantic model maps to a MongoDB collection (lowercased class name).
- Landlord  -> "landlord"
- Property  -> "property"
- WorkOrder -> "workorder"
- Certificate -> "certificate"
- ActivityLog -> "activitylog"
- User -> "user"
- TenantIssue -> "tenantissue"
- LinkToken -> "linktoken"
"""

from pydantic import BaseModel, Field, EmailStr
from typing import Optional, Literal, List
from datetime import date, datetime

class Location(BaseModel):
    lat: float
    lng: float

class Landlord(BaseModel):
    name: str = Field(..., description="Full name or company name")
    email: Optional[EmailStr] = Field(None, description="Contact email")
    phone: Optional[str] = Field(None, description="Primary contact phone")
    address: Optional[str] = Field(None, description="Registered address")
    notes: Optional[str] = Field(None, description="Additional notes")

class Property(BaseModel):
    landlord_id: str = Field(..., description="Related landlord id (string)")
    address_line1: str = Field(..., description="Address line 1")
    address_line2: Optional[str] = Field(None, description="Address line 2")
    city: str = Field(..., description="City")
    postcode: str = Field(..., description="Postal code")
    bedrooms: Optional[int] = Field(None, ge=0, description="Number of bedrooms")
    gas_safe_required: bool = Field(True, description="Gas safety certificate required")
    eicr_required: bool = Field(True, description="Electrical installation condition report required")
    epc_required: bool = Field(True, description="Energy Performance Certificate required")
    rent_amount: Optional[float] = Field(None, ge=0, description="Monthly rent amount")
    rent_day: Optional[int] = Field(None, ge=1, le=28, description="Day of month rent is due (1-28)")

class WorkOrder(BaseModel):
    property_id: str = Field(..., description="Related property id (string)")
    title: str = Field(..., description="Work title")
    description: Optional[str] = Field(None, description="Detailed description")
    category: Literal['maintenance','repair','compliance','inspection'] = Field('maintenance', description="Work category")
    status: Literal['new','scheduled','in_progress','completed','cancelled'] = Field('new', description="Current status")
    scheduled_for: Optional[date] = Field(None, description="Scheduled date")
    cost: Optional[float] = Field(None, ge=0, description="Estimated or final cost")
    photos: Optional[List[str]] = Field(default=None, description="List of photo URLs")
    operative_id: Optional[str] = Field(None, description="Assigned operative user id")
    started_at: Optional[datetime] = Field(None, description="When operative started the job")
    started_location: Optional[Location] = Field(None, description="Geolocation where job was started")
    completed_at: Optional[datetime] = Field(None, description="When operative completed the job")
    completed_location: Optional[Location] = Field(None, description="Geolocation where job was completed")

class Certificate(BaseModel):
    property_id: str = Field(..., description="Related property id (string)")
    type: Literal['gas_safety','eicr','epc','boiler_service','smoke_alarm'] = Field(..., description="Certificate type")
    certificate_number: Optional[str] = Field(None, description="Certificate/reference number")
    issue_date: Optional[date] = Field(None, description="Issue date")
    expiry_date: Optional[date] = Field(None, description="Expiry date")
    uploaded_by: Optional[str] = Field(None, description="Name of person uploading/issuing")
    notes: Optional[str] = Field(None, description="Additional notes")
    file_path: Optional[str] = Field(None, description="Server path to uploaded file if any")
    file_name: Optional[str] = Field(None, description="Original file name if uploaded")

class ActivityLog(BaseModel):
    actor: Optional[str] = Field(None, description="User performing the action")
    role: Optional[str] = Field(None, description="Role of actor at time of action")
    action: str = Field(..., description="Action type")
    entity: str = Field(..., description="Entity type: landlord/property/workorder/certificate/tenantissue")
    entity_id: Optional[str] = Field(None, description="Entity id string")
    details: Optional[str] = Field(None, description="Additional context")
    at: Optional[datetime] = Field(default_factory=datetime.utcnow, description="Timestamp")

class User(BaseModel):
    email: EmailStr
    name: Optional[str] = None
    role: Literal['admin','manager','viewer','operative'] = 'viewer'
    auth_token: Optional[str] = None

class TenantIssue(BaseModel):
    property_id: str = Field(...)
    tenant_name: Optional[str] = None
    tenant_contact: Optional[str] = None
    description: str = Field(...)
    priority: Literal['low','medium','high'] = 'medium'
    status: Literal['reported','acknowledged','in_progress','resolved','closed'] = 'reported'
    photos: Optional[List[str]] = None

class LinkToken(BaseModel):
    token: str
    property_id: str
    type: Literal['tenant_report'] = 'tenant_report'
    expires_at: Optional[datetime] = None
