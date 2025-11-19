"""
Database Schemas for Property Asset Management

Each Pydantic model maps to a MongoDB collection (lowercased class name).
- Landlord  -> "landlord"
- Property  -> "property"
- WorkOrder -> "workorder"
- Certificate -> "certificate"
"""

from pydantic import BaseModel, Field, EmailStr
from typing import Optional, Literal
from datetime import date

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

class WorkOrder(BaseModel):
    property_id: str = Field(..., description="Related property id (string)")
    title: str = Field(..., description="Work title")
    description: Optional[str] = Field(None, description="Detailed description")
    category: Literal['maintenance','repair','compliance','inspection'] = Field('maintenance', description="Work category")
    status: Literal['new','scheduled','in_progress','completed','cancelled'] = Field('new', description="Current status")
    scheduled_for: Optional[date] = Field(None, description="Scheduled date")
    cost: Optional[float] = Field(None, ge=0, description="Estimated or final cost")

class Certificate(BaseModel):
    property_id: str = Field(..., description="Related property id (string)")
    type: Literal['gas_safety','eicr','epc','boiler_service','smoke_alarm'] = Field(..., description="Certificate type")
    certificate_number: Optional[str] = Field(None, description="Certificate/reference number")
    issue_date: Optional[date] = Field(None, description="Issue date")
    expiry_date: Optional[date] = Field(None, description="Expiry date")
    uploaded_by: Optional[str] = Field(None, description="Name of person uploading/issuing")
    notes: Optional[str] = Field(None, description="Additional notes")
