"""Step 2: decide Low / Normal / High in Python, NOT by the AI.

Normal ranges depend on age and sex. Ranges below are common adult/child reference
intervals; labs differ slightly, so we fall back to the printed range when we don't
know a test. (For a real product these would be reviewed by a doctor.)
"""
import re
from dataclasses import dataclass, asdict
from typing import Optional

# Each test: aliases, unit, and a list of ranges.
# Range: (sex, age_min, age_max, low, high)   sex = "M" / "F" / "A" (any)
# crit: (critical_low, critical_high) -> values that need urgent attention
REFERENCE = {
    "Haemoglobin": {
        "aliases": ["hemoglobin", "haemoglobin", "hb", "hgb"], "unit": "g/dL",
        "ranges": [("A", 0, 1, 10.0, 14.0), ("A", 1, 6, 11.0, 14.0), ("A", 6, 12, 11.5, 15.5),
                   ("M", 12, 18, 13.0, 16.0), ("F", 12, 18, 12.0, 16.0),
                   ("M", 18, 200, 13.0, 17.0), ("F", 18, 200, 12.0, 15.5)],
        "crit": (7.0, 20.0)},
    "RBC Count": {
        "aliases": ["rbc", "rbccount", "redbloodcells", "totalrbc", "redcellcount"],
        "unit": "million/µL",
        "ranges": [("A", 0, 12, 4.0, 5.2), ("M", 12, 200, 4.5, 5.9), ("F", 12, 200, 4.0, 5.2)],
        "crit": (2.5, 7.5)},
    "PCV (Haematocrit)": {
        "aliases": ["pcv", "hct", "hematocrit", "haematocrit", "packedcellvolume"], "unit": "%",
        "ranges": [("A", 0, 12, 35, 45), ("M", 12, 200, 40, 50), ("F", 12, 200, 36, 46)],
        "crit": (20, 60)},
    "MCV": {"aliases": ["mcv", "meancorpuscularvolume"], "unit": "fL",
            "ranges": [("A", 0, 200, 80, 100)], "crit": (None, None)},
    "MCH": {"aliases": ["mch", "meancorpuscularhemoglobin", "meancorpuscularhaemoglobin"],
            "unit": "pg", "ranges": [("A", 0, 200, 27, 33)], "crit": (None, None)},
    "MCHC": {"aliases": ["mchc"], "unit": "g/dL",
             "ranges": [("A", 0, 200, 32, 36)], "crit": (None, None)},
    "RDW": {"aliases": ["rdw", "rdwcv"], "unit": "%",
            "ranges": [("A", 0, 200, 11.5, 14.5)], "crit": (None, None)},
    "Total WBC Count": {
        "aliases": ["wbc", "totalwbccount", "wbccount", "tlc", "totalleucocytecount",
                    "totalleukocytecount", "totalcount"], "unit": "/cu.mm",
        "ranges": [("A", 0, 12, 5000, 13000), ("A", 12, 200, 4000, 11000)],
        "crit": (2000, 30000)},
    "Neutrophils": {"aliases": ["neutrophils", "neutrophil", "polymorphs"], "unit": "%",
                    "ranges": [("A", 0, 200, 40, 75)], "crit": (None, None)},
    "Lymphocytes": {"aliases": ["lymphocytes", "lymphocyte"], "unit": "%",
                    "ranges": [("A", 0, 200, 20, 45)], "crit": (None, None)},
    "Eosinophils": {"aliases": ["eosinophils", "eosinophil"], "unit": "%",
                    "ranges": [("A", 0, 200, 1, 6)], "crit": (None, None)},
    "Monocytes": {"aliases": ["monocytes", "monocyte"], "unit": "%",
                  "ranges": [("A", 0, 200, 2, 10)], "crit": (None, None)},
    "Basophils": {"aliases": ["basophils", "basophil"], "unit": "%",
                  "ranges": [("A", 0, 200, 0, 1)], "crit": (None, None)},
    "Platelet Count": {
        "aliases": ["platelet", "platelets", "plateletcount", "plt"], "unit": "/cu.mm",
        "ranges": [("A", 0, 200, 150000, 450000)], "crit": (50000, 1000000)},
    "ESR": {"aliases": ["esr"], "unit": "mm/hr",
            "ranges": [("M", 0, 200, 0, 15), ("F", 0, 200, 0, 20)], "crit": (None, None)},
    "Fasting Blood Sugar": {
        "aliases": ["fbs", "fastingbloodsugar", "fastingglucose", "glucosefasting",
                    "fastingplasmaglucose", "bloodsugarfasting"], "unit": "mg/dL",
        "ranges": [("A", 0, 200, 70, 99)], "crit": (54, 400)},
    "Post Prandial Blood Sugar": {
        "aliases": ["ppbs", "postprandialbloodsugar", "postprandialglucose",
                    "glucosepp", "bloodsugarpp"], "unit": "mg/dL",
        "ranges": [("A", 0, 200, 70, 139)], "crit": (54, 400)},
    "Random Blood Sugar": {
        "aliases": ["rbs", "randombloodsugar", "randomglucose"], "unit": "mg/dL",
        "ranges": [("A", 0, 200, 70, 139)], "crit": (54, 400)},
    "HbA1c": {"aliases": ["hba1c", "glycatedhaemoglobin", "glycatedhemoglobin",
                          "glycosylatedhemoglobin", "a1c"], "unit": "%",
              "ranges": [("A", 0, 200, 4.0, 5.6)], "crit": (None, 14)},
    "Total Cholesterol": {"aliases": ["totalcholesterol", "cholesterol", "cholesteroltotal"],
                          "unit": "mg/dL", "ranges": [("A", 0, 200, 0, 199)], "crit": (None, None)},
    "LDL Cholesterol": {"aliases": ["ldl", "ldlcholesterol", "ldlc"], "unit": "mg/dL",
                        "ranges": [("A", 0, 200, 0, 99)], "crit": (None, None)},
    "HDL Cholesterol": {"aliases": ["hdl", "hdlcholesterol", "hdlc"], "unit": "mg/dL",
                        "ranges": [("M", 0, 200, 40, 100), ("F", 0, 200, 50, 100)],
                        "crit": (None, None)},
    "Triglycerides": {"aliases": ["triglycerides", "triglyceride", "tg"], "unit": "mg/dL",
                      "ranges": [("A", 0, 200, 0, 149)], "crit": (None, 1000)},
    "TSH": {"aliases": ["tsh", "thyroidstimulatinghormone"], "unit": "µIU/mL",
            "ranges": [("A", 0, 200, 0.4, 4.0)], "crit": (None, None)},
    "Creatinine": {"aliases": ["creatinine", "serumcreatinine", "screatinine"], "unit": "mg/dL",
                   "ranges": [("A", 0, 12, 0.3, 0.7), ("M", 12, 200, 0.7, 1.3),
                              ("F", 12, 200, 0.6, 1.1)], "crit": (None, 5.0)},
    "Blood Urea": {"aliases": ["urea", "bloodurea", "serumurea"], "unit": "mg/dL",
                   "ranges": [("A", 0, 200, 15, 40)], "crit": (None, 150)},
    "Uric Acid": {"aliases": ["uricacid", "serumuricacid"], "unit": "mg/dL",
                  "ranges": [("M", 0, 200, 3.4, 7.0), ("F", 0, 200, 2.4, 6.0)],
                  "crit": (None, None)},
    "SGOT (AST)": {"aliases": ["sgot", "ast", "sgotast", "aspartateaminotransferase"],
                   "unit": "U/L", "ranges": [("A", 0, 200, 0, 40)], "crit": (None, 1000)},
    "SGPT (ALT)": {"aliases": ["sgpt", "alt", "sgptalt", "alanineaminotransferase"],
                   "unit": "U/L", "ranges": [("A", 0, 200, 0, 40)], "crit": (None, 1000)},
    "Total Bilirubin": {"aliases": ["totalbilirubin", "bilirubintotal", "serumbilirubintotal"],
                        "unit": "mg/dL", "ranges": [("A", 0, 200, 0.2, 1.2)], "crit": (None, 15)},
    "Vitamin D": {"aliases": ["vitamind", "vitd", "25ohvitamind", "vitamind325oh",
                              "25hydroxyvitamind"], "unit": "ng/mL",
                  "ranges": [("A", 0, 200, 30, 100)], "crit": (None, None)},
    "Vitamin B12": {"aliases": ["vitaminb12", "b12", "vitb12", "cyanocobalamin"],
                    "unit": "pg/mL", "ranges": [("A", 0, 200, 200, 900)], "crit": (None, None)},
    "Ferritin": {"aliases": ["ferritin", "serumferritin"], "unit": "ng/mL",
                 "ranges": [("M", 0, 200, 30, 400), ("F", 0, 200, 13, 150)], "crit": (None, None)},
    "Sodium": {"aliases": ["sodium", "na", "serumsodium"], "unit": "mmol/L",
               "ranges": [("A", 0, 200, 135, 145)], "crit": (120, 160)},
    "Potassium": {"aliases": ["potassium", "k", "serumpotassium"], "unit": "mmol/L",
                  "ranges": [("A", 0, 200, 3.5, 5.1)], "crit": (2.5, 6.5)},
    "Calcium": {"aliases": ["calcium", "serumcalcium", "ca"], "unit": "mg/dL",
                "ranges": [("A", 0, 200, 8.5, 10.5)], "crit": (6.5, 13)},
}

_ALIAS_INDEX = {re.sub(r"[^a-z0-9]", "", a): key
                for key, info in REFERENCE.items() for a in info["aliases"]}


@dataclass
class FlaggedResult:
    test_name: str            # standard name
    original_name: str        # as printed
    value_text: str
    value: Optional[float]
    unit: str
    low: Optional[float]
    high: Optional[float]
    range_source: str         # "age/sex reference" or "printed on report"
    status: str               # NORMAL / LOW / HIGH / CRITICAL LOW / CRITICAL HIGH / TEXT / UNKNOWN
    note: str = ""

    def to_dict(self):
        return asdict(self)


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def _match_test(name: str) -> Optional[str]:
    n = _norm(name)
    if n in _ALIAS_INDEX:
        return _ALIAS_INDEX[n]
    for alias, key in _ALIAS_INDEX.items():       # e.g. "haemoglobinhb"
        if len(alias) >= 4 and alias in n:
            return key
    return None


def _to_float(text: Optional[str]) -> Optional[float]:
    if not text:
        return None
    m = re.search(r"-?\d+(?:\.\d+)?", text.replace(",", ""))
    return float(m.group()) if m else None


def parse_age(age_text) -> Optional[float]:
    if age_text is None:
        return None
    if isinstance(age_text, (int, float)):
        return float(age_text)
    v = _to_float(str(age_text))
    if v is None:
        return None
    if "month" in str(age_text).lower():
        return v / 12
    return v


def _pick_range(key: str, age: Optional[float], sex: Optional[str]):
    sex = (sex or "").upper()[:1]
    age = 30 if age is None else age
    best = None
    for r_sex, a_min, a_max, low, high in REFERENCE[key]["ranges"]:
        if not (a_min <= age < a_max):
            continue
        if r_sex == sex:
            return low, high
        if r_sex == "A" or best is None:
            best = (low, high)
    return best or (None, None)


def _scale_value(key: str, value: float, unit: str) -> float:
    """Bring counts written in lakhs or thousands to /cu.mm."""
    u = (unit or "").lower()
    if key == "Platelet Count":
        if "lakh" in u or value < 10:
            return value * 100000
        if value < 1000:                       # e.g. 250 x10^3/µL
            return value * 1000
    if key == "Total WBC Count" and value < 200:   # e.g. 5.5 x10^3/µL
        return value * 1000
    if key == "RBC Count" and value > 100:          # e.g. 4500000 /cumm
        return value / 1_000_000
    return value


def _parse_printed_range(text: Optional[str]):
    if not text:
        return None, None
    nums = re.findall(r"\d+(?:\.\d+)?", text.replace(",", ""))
    if len(nums) >= 2:
        return float(nums[0]), float(nums[1])
    if nums and "<" in text:
        return None, float(nums[0])
    if nums and ">" in text:
        return float(nums[0]), None
    return None, None


def flag_result(test_name, value_text, unit, printed_range, age, sex) -> FlaggedResult:
    key = _match_test(test_name)
    value = _to_float(value_text)

    if value is None:
        return FlaggedResult(key or test_name, test_name, value_text or "", None, unit or "",
                             None, None, "", "TEXT", "Descriptive result, read with your doctor.")

    if key:
        value = _scale_value(key, value, unit)
        low, high = _pick_range(key, age, sex)
        out_unit, source = REFERENCE[key]["unit"], "age/sex reference"
        crit_low, crit_high = REFERENCE[key]["crit"]
    else:
        low, high = _parse_printed_range(printed_range)
        out_unit, source = unit or "", "printed on report"
        crit_low = crit_high = None
        if low is None and high is None:
            return FlaggedResult(test_name, test_name, value_text, value, out_unit,
                                 None, None, "", "UNKNOWN", "No reference range available.")

    if crit_low is not None and value < crit_low:
        status = "CRITICAL LOW"
    elif crit_high is not None and value > crit_high:
        status = "CRITICAL HIGH"
    elif low is not None and value < low:
        status = "LOW"
    elif high is not None and value > high:
        status = "HIGH"
    else:
        status = "NORMAL"

    note = ""
    if high and value > high * 3:
        note = ("Very far outside the normal range. This may be a printing or reading error; "
                "please check the original report and confirm with the lab or your doctor.")
    return FlaggedResult(key or test_name, test_name, value_text, value, out_unit,
                         low, high, source, status, note)


def flag_all(lab_results, age, sex) -> list[FlaggedResult]:
    return [flag_result(r.test_name, r.value, r.unit, r.reference_range, age, sex)
            for r in lab_results]


def bmi_info(weight_kg: Optional[float], height_cm: Optional[float]):
    if not weight_kg or not height_cm:
        return None
    bmi = weight_kg / ((height_cm / 100) ** 2)
    # Asian (India) cut-offs
    if bmi < 18.5:
        cat = "Underweight"
    elif bmi < 23:
        cat = "Normal"
    elif bmi < 25:
        cat = "Overweight"
    else:
        cat = "Obese"
    return round(bmi, 1), cat