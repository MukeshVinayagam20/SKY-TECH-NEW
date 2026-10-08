"""Step 1: read the document image(s) and pull out structured data."""
from .llm import call_llm_json
from .schemas import ExtractedDocument

PROMPT = """You are a medical document extraction system for Indian healthcare records.
The document may be printed or handwritten, in English, Tamil, Hindi, or mixed.

Extract information EXACTLY as written. Rules:
- Never guess a medicine name, dose, or value. If unclear, add it to "unreadable_parts"
  and give a low confidence score.
- test_name must be the individual test (e.g. "MCV", "MCH", "Platelet Count"),
  NEVER a section heading like "RBC Indices", "Total WBC Count" header or "Platelets".
- Read each row straight across: the value and reference range must come from the SAME row
  as the test name.
- If a reference range has separate male/female values, copy it fully.
- Dosage patterns like "1-0-1" mean morning-afternoon-night; keep the original
  in "dosage" and explain it in "frequency".
- Dates must be YYYY-MM-DD. Indian dates are DD/MM/YYYY.
- Keep lab values and units exactly as printed.
- Text results (e.g. "Normocytic, Normochromic", "Adequate") go in value as text.
- confidence: 1.0 = clearly printed, 0.5 = partly legible, <0.4 = uncertain.
"""


def extract_document(images: list[bytes]) -> ExtractedDocument:
    return call_llm_json(PROMPT, ExtractedDocument, images)