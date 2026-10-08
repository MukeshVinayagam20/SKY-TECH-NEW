from pydantic import BaseModel, Field
from typing import Optional, Literal

class Medicine(BaseModel):
    name: str
    strength: Optional[str] = None          # "500 mg"
    form: Optional[str] = None              # tablet, syrup, injection
    dosage: Optional[str] = None            # "1-0-1"
    frequency: Optional[str] = None         # "twice daily"
    timing: Optional[str] = None            # "after food"
    duration: Optional[str] = None          # "5 days"
    confidence: float = Field(ge=0, le=1)

class LabResult(BaseModel):
    test_name: str
    value: Optional[str] = None             # keep as string; "Positive", "12.5"
    unit: Optional[str] = None
    reference_range: Optional[str] = None   # as printed on the report
    confidence: float = Field(ge=0, le=1)

class Diagnosis(BaseModel):
    name: str
    confidence: float = Field(ge=0, le=1)

class ExtractedDocument(BaseModel):
    document_type: Literal["prescription", "lab_report",
                           "discharge_summary", "diagnostic_report", "other"]
    document_date: Optional[str] = None     # YYYY-MM-DD
    patient_name: Optional[str] = None
    patient_age: Optional[str] = None
    patient_gender: Optional[str] = None
    doctor_name: Optional[str] = None
    facility_name: Optional[str] = None
    languages_detected: list[str] = []
    is_handwritten: bool = False
    medicines: list[Medicine] = []
    lab_results: list[LabResult] = []
    diagnoses: list[Diagnosis] = []
    advice: list[str] = []
    follow_up_date: Optional[str] = None
    unreadable_parts: list[str] = []        # what couldn't be read