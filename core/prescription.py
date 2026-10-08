"""Doctor-in-the-loop prescription workflow.

1. AI drafts treatment SUGGESTIONS from the abnormal results (generic names, no doses).
2. Only the doctor sees the draft. The doctor edits medicines, strength, timing
   (morning / afternoon / night), before/after food and duration.
3. The doctor signs (name + registration number) and approves.
4. Only the APPROVED prescription is shown to the patient and exported as PDF.
"""
import json
from datetime import datetime
from pathlib import Path
from typing import Literal
from pydantic import BaseModel
from .llm import call_llm_json
from .i18n import fmt_value, fmt_range

ABNORMAL = ("LOW", "HIGH", "CRITICAL LOW", "CRITICAL HIGH")
FOOD_OPTIONS = ["After food", "Before food", "With food", "Empty stomach", "Any time"]
STORE = Path(__file__).resolve().parent.parent / ".prescriptions"


# ---------------- AI draft (doctor only) ----------------
class MedicineSuggestion(BaseModel):
    generic_name: str
    purpose: str
    related_tests: list[str]
    form: str                                   # tablet / syrup / capsule ...
    suggested_slots: list[Literal["morning", "afternoon", "night"]]
    suggested_food: Literal["After food", "Before food", "With food", "Empty stomach", "Any time"]
    suggested_duration: str                     # e.g. "30 days", "until review"
    cautions: list[str]


class TreatmentDraft(BaseModel):
    clinical_note: str                          # short reasoning for the doctor
    medicines: list[MedicineSuggestion]
    tests_to_consider: list[str]
    lifestyle_advice: list[str]
    referral_or_urgent_action: str              # "" if none


DRAFT_PROMPT = """You are a clinical decision-support assistant helping a LICENSED DOCTOR in India.
Your output is a DRAFT that the doctor will review, edit and approve or reject.
The patient will NOT see this draft.

PATIENT: {profile}
DOCUMENT: {doc_type}; diagnoses written on it: {diagnoses}
MEDICINES ALREADY PRESCRIBED ON THE DOCUMENT: {current_meds}

ABNORMAL RESULTS (status decided by a rule engine):
{abnormal}

NORMAL RESULTS: {normal}

Write the draft:
- clinical_note: 2-4 sentences: the likely pattern, and what must be confirmed first.
- medicines: ONLY where the abnormal results reasonably support it, using standard first-line
  options. Use GENERIC names only (no brands). Do NOT give doses or strengths - the doctor sets them.
  For each: purpose, related_tests, form, usual timing (suggested_slots, suggested_food),
  suggested_duration, and cautions (interactions, side effects, who should avoid it).
  If a result looks like a lab/printing error or needs confirmation first, do NOT suggest a
  medicine for it - put a repeat test in tests_to_consider instead.
  Never suggest antibiotics, steroids, opioids, sedatives or other controlled drugs.
  It is fine to return an empty medicines list.
- tests_to_consider: confirmatory or follow-up tests.
- lifestyle_advice: 2-4 short points.
- referral_or_urgent_action: what to do about CRITICAL results ("" if none).
"""


def draft_treatment(doc, flags, profile: dict) -> TreatmentDraft:
    abnormal = [f for f in flags if f.status in ABNORMAL]
    normal = [f.test_name for f in flags if f.status == "NORMAL"]
    ab_text = "\n".join(f"- {f.test_name}: {fmt_value(f)} (normal {fmt_range(f)}) STATUS {f.status}"
                        + (f" NOTE: {f.note}" if f.note else "") for f in abnormal) or "None"
    current = ", ".join(f"{m.name} {m.strength or ''} {m.dosage or ''}".strip()
                        for m in doc.medicines) or "None"
    prompt = DRAFT_PROMPT.format(
        profile=", ".join(f"{k}: {v}" for k, v in profile.items() if v) or "unknown",
        doc_type=doc.document_type,
        diagnoses=", ".join(d.name for d in doc.diagnoses) or "None",
        current_meds=current, abnormal=ab_text, normal=", ".join(normal) or "None")
    return call_llm_json(prompt, TreatmentDraft, task="text")


# ---------------- Approved prescription ----------------
class PrescribedMedicine(BaseModel):
    name: str
    strength: str
    form: str = "Tablet"
    morning: bool = False
    afternoon: bool = False
    night: bool = False
    food: str = "After food"
    duration: str = ""
    instructions: str = ""

    @property
    def pattern(self) -> str:                   # 1-0-1 style
        return f"{int(self.morning)}-{int(self.afternoon)}-{int(self.night)}"

    @property
    def when(self) -> str:
        parts = [p for p, on in (("Morning", self.morning), ("Afternoon", self.afternoon),
                                 ("Night", self.night)) if on]
        return ", ".join(parts)


class Prescription(BaseModel):
    doctor_name: str
    registration_no: str
    approved_at: str
    medicines: list[PrescribedMedicine]
    tests: list[str] = []
    advice: str = ""
    review_after: str = ""


def validate_rows(rows: list[dict]) -> tuple[list[PrescribedMedicine], list[str]]:
    """Turn the doctor's edited table into medicines, collecting any problems."""
    meds, problems = [], []
    for i, r in enumerate(rows, start=1):
        if not r.get("Include"):
            continue
        name = (r.get("Medicine") or "").strip()
        label = name or f"Row {i}"
        if not name:
            problems.append(f"Row {i}: medicine name is empty.")
        if not (r.get("Strength") or "").strip():
            problems.append(f"{label}: enter the strength / dose (e.g. 100 mg).")
        if not (r.get("Morning") or r.get("Afternoon") or r.get("Night")):
            problems.append(f"{label}: tick at least one of Morning / Afternoon / Night.")
        if not (r.get("Duration") or "").strip():
            problems.append(f"{label}: enter the duration (e.g. 30 days).")
        meds.append(PrescribedMedicine(
            name=name, strength=(r.get("Strength") or "").strip(), form=r.get("Form") or "Tablet",
            morning=bool(r.get("Morning")), afternoon=bool(r.get("Afternoon")),
            night=bool(r.get("Night")), food=r.get("Food") or "After food",
            duration=(r.get("Duration") or "").strip(),
            instructions=(r.get("Instructions") or "").strip()))
    return meds, problems


def draft_to_rows(draft: TreatmentDraft) -> list[dict]:
    return [{"Include": True, "Medicine": m.generic_name, "Strength": "", "Form": m.form.title(),
             "Morning": "morning" in m.suggested_slots, "Afternoon": "afternoon" in m.suggested_slots,
             "Night": "night" in m.suggested_slots, "Food": m.suggested_food,
             "Duration": m.suggested_duration, "Instructions": ""}
            for m in draft.medicines]


def approve(doctor_name, reg_no, meds, tests, advice, review_after) -> Prescription:
    return Prescription(doctor_name=doctor_name.strip(), registration_no=reg_no.strip(),
                        approved_at=datetime.now().strftime("%d-%m-%Y %H:%M"),
                        medicines=meds, tests=tests, advice=advice.strip(),
                        review_after=review_after.strip())


def save(key: str, rx: Prescription):
    STORE.mkdir(exist_ok=True)
    (STORE / f"{key}.json").write_text(rx.model_dump_json(indent=2), encoding="utf-8")


def load(key: str):
    path = STORE / f"{key}.json"
    if path.exists():
        try:
            return Prescription.model_validate_json(path.read_text(encoding="utf-8"))
        except Exception:
            return None
    return None