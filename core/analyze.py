"""Step 3: turn extracted data + flags into a simple, detailed report for the patient.

The report is always written in English first (small local models write much better English),
then translated to Tamil in small batches if the user chooses Tamil.
"""
import json
from typing import Literal
from pydantic import BaseModel
from .llm import call_llm_json
from .rules import FlaggedResult, _norm, _match_test
from .i18n import has_tamil, fmt_range, fmt_value

ABNORMAL = ("LOW", "HIGH", "CRITICAL LOW", "CRITICAL HIGH")


class FindingExplanation(BaseModel):
    test_name: str
    what_it_measures: str
    what_your_result_means: str
    possible_causes: list[str]
    food_and_lifestyle_tips: list[str]
    what_your_doctor_may_do: list[str]
    urgency: Literal["routine", "see_doctor_soon", "urgent"]


class MedicineExplanation(BaseModel):
    name: str
    used_for: str
    how_to_take: str
    common_side_effects: list[str]
    precautions: list[str]


class HealthReport(BaseModel):
    overall_summary: str
    findings: list[FindingExplanation]
    medicines: list[MedicineExplanation]
    diet_and_lifestyle: list[str]
    questions_for_doctor: list[str]
    warning_signs: list[str]


PROMPT = """You are a caring health educator explaining a medical report to a patient in India
who has no medical background. Write at the level of a 12-year-old. Short sentences. English only.

PATIENT: {profile}
DOCUMENT TYPE: {doc_type}
DIAGNOSES WRITTEN ON THE DOCUMENT: {diagnoses}

LAB RESULTS (status already decided by a rule engine - DO NOT change any status or range,
and NEVER call a result normal if its STATUS is not NORMAL):
{results}

MEDICINES WRITTEN BY THE DOCTOR:
{medicines}

Write the report:
- overall_summary: 3-5 sentences, the big picture for this person (use their age/sex/BMI).
  Mention every result that is not NORMAL.
- findings: ONE entry for EACH of these tests, in this order: {abnormal_list}
  * test_name: copy exactly from the list.
  * what_your_result_means: say the value, the normal range for their age and sex,
    and whether it is low or high and by how much, in plain words.
  * possible_causes: 2-4 common causes, most common first.
  * food_and_lifestyle_tips: practical Indian food examples where useful.
  * what_your_doctor_may_do: further tests or the general TYPE of treatment doctors
    commonly consider (e.g. "may check iron levels and may suggest iron tablets").
  * urgency: "urgent" for CRITICAL status, otherwise "routine" or "see_doctor_soon".
  * If a result has a NOTE about a possible reading error, mention it.
- medicines: for each medicine listed: what it is usually used for, how to take it as written
  (explain patterns like 1-0-1), common side effects, precautions. Empty list if none.
- diet_and_lifestyle: 4-6 overall tips.
- questions_for_doctor: 3-5 good questions to ask at the next visit.
- warning_signs: symptoms that mean they should see a doctor quickly.

SAFETY RULES (very important):
- Never prescribe. Never give a medicine dose, brand name or "take X". Never tell the
  patient to start, stop or change a medicine. Always say the doctor decides treatment.
- Never give a definite diagnosis. Use "can be a sign of", "may mean".
- Do not frighten. Be calm, kind and honest.
"""


def _fmt_results(flags: list[FlaggedResult]) -> str:
    lines = []
    for f in flags:
        line = f"- {f.test_name}: {fmt_value(f)} | normal: {fmt_range(f)} | STATUS: {f.status}"
        if f.note:
            line += f" | NOTE: {f.note}"
        lines.append(line)
    return "\n".join(lines) or "None"


def _fallback_finding(f: FlaggedResult) -> FindingExplanation:
    direction = "lower" if "LOW" in f.status else "higher"
    return FindingExplanation(
        test_name=f.test_name,
        what_it_measures=f"{f.test_name} is one of the values checked in your report.",
        what_your_result_means=(f"Your value is {fmt_value(f)}. This is {direction} than the "
                                f"normal range for your age and sex ({fmt_range(f)}). {f.note}").strip(),
        possible_causes=["There can be many reasons. Your doctor can explain what it means for you."],
        food_and_lifestyle_tips=["Eat a balanced diet, drink enough water and sleep well."],
        what_your_doctor_may_do=["Your doctor may repeat the test or ask for more tests."],
        urgency="urgent" if f.status.startswith("CRITICAL") else "see_doctor_soon",
    )


def _fix_findings(report: HealthReport, flags: list[FlaggedResult]) -> HealthReport:
    """Make sure there is exactly one finding per abnormal result, in the right order,
    and nothing about results that are actually normal (small models sometimes mix this up)."""
    abnormal = [f for f in flags if f.status in ABNORMAL]
    remaining = list(report.findings)
    fixed = []
    for f in abnormal:
        target = _norm(f.test_name)
        match = None
        for x in remaining:
            k = _norm(x.test_name)
            if k and (k == target or _match_test(x.test_name) == f.test_name
                      or k in target or target in k):
                match = x
                break
        if match:
            remaining.remove(match)
        else:
            match = _fallback_finding(f)
        match.test_name = f.test_name
        if f.status.startswith("CRITICAL"):
            match.urgency = "urgent"
        fixed.append(match)
    report.findings = fixed
    return report


def build_report(doc, flags: list[FlaggedResult], profile: dict) -> HealthReport:
    profile_text = ", ".join(f"{k}: {v}" for k, v in profile.items() if v not in (None, "", 0))
    meds = "\n".join(f"- {m.name} {m.strength or ''} | dosage: {m.dosage or ''} "
                     f"{m.frequency or ''} {m.timing or ''} | duration: {m.duration or ''}"
                     for m in doc.medicines) or "None"
    abnormal = [f.test_name for f in flags if f.status in ABNORMAL]
    prompt = PROMPT.format(
        profile=profile_text or "unknown",
        doc_type=doc.document_type,
        diagnoses=", ".join(d.name for d in doc.diagnoses) or "None",
        results=_fmt_results(flags),
        medicines=meds,
        abnormal_list=", ".join(abnormal) or "(none - return an empty list)",
    )
    report = call_llm_json(prompt, HealthReport, task="text")
    return _fix_findings(report, flags)


# ---------------- Translation ----------------
class _Items(BaseModel):
    items: list[str]


TRANSLATE_PROMPT = """Translate EACH item in the list below from English into simple,
everyday {language} that an ordinary patient in Tamil Nadu can easily understand.

Rules:
- Every output item MUST be written in {language} script.
- Keep numbers and units exactly as they are (e.g. 36 %, 150000 - 450000 /cu.mm).
- Keep medical test names and medicine names in English inside brackets after the
  {language} word, e.g. ஹீமோகுளோபின் (Haemoglobin).
- Keep the exact meaning. Do not add or remove information.
- Return exactly {n} items, in the same order.

ITEMS (JSON list):
{items}
"""

SKIP_KEYS = {"test_name", "name", "urgency"}
BATCH = 20                      # bigger batches = fewer slow AI calls


def _translate_batch(texts: list[str], language: str) -> list[str]:
    for _ in range(2):                                  # one retry
        try:
            out = call_llm_json(TRANSLATE_PROMPT.format(
                language=language, n=len(texts),
                items=json.dumps(texts, ensure_ascii=False, indent=1)), _Items, task="text").items
        except Exception as e:
            print(f"[translate] batch failed: {e}")
            continue
        if len(out) == len(texts) and sum(has_tamil(t) for t in out) >= len(texts) * 0.7:
            return out
        print("[translate] bad batch (wrong count or not Tamil), retrying")
    return texts                                          # keep English if it fails twice


def translate_report(report: HealthReport, language: str, progress=None) -> HealthReport:
    """progress: optional function(done, total) to show a progress bar."""
    if language == "English":
        return report
    data = report.model_dump()
    refs, texts = [], []

    def walk(node):
        items = node.items() if isinstance(node, dict) else enumerate(node)
        for key, value in items:
            if isinstance(node, dict) and key in SKIP_KEYS:
                continue
            if isinstance(value, str):
                if value.strip():
                    refs.append((node, key))
                    texts.append(value)
            elif isinstance(value, (dict, list)):
                walk(value)

    walk(data)
    translated = []
    total = (len(texts) + BATCH - 1) // BATCH
    for n, i in enumerate(range(0, len(texts), BATCH)):
        if progress:
            progress(n, total)
        translated += _translate_batch(texts[i:i + BATCH], language)
    if progress:
        progress(total, total)
    for (container, key), text in zip(refs, translated):
        container[key] = text
    return HealthReport.model_validate(data)