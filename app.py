import os
import secrets
import io

from flask import Flask, render_template, request, session, jsonify, send_file
from dotenv import load_dotenv

from core.ingest import file_to_images
from core.extract import extract_document
from core.rules import flag_all, parse_age, bmi_info, FlaggedResult
from core.analyze import build_report, ABNORMAL
from core.i18n import fmt_range, fmt_value, profile_lines
from core.schemas import ExtractedDocument
from core.analyze import HealthReport
from core import cache
from core import prescription as rxmod

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", secrets.token_hex(16))
app.config["MAX_CONTENT_LENGTH"] = 15 * 1024 * 1024  # 15 MB, matches old Streamlit limit

STATUS_ICON = {"NORMAL": "🟢", "LOW": "🔵", "HIGH": "🟠", "CRITICAL LOW": "🔴",
               "CRITICAL HIGH": "🔴", "TEXT": "⚪", "UNKNOWN": "⚪"}
STATUS_BG = {"NORMAL": "#e8f5e9", "LOW": "#e3f2fd", "HIGH": "#fff3e0",
             "CRITICAL LOW": "#ffcdd2", "CRITICAL HIGH": "#ffcdd2"}
URGENCY_LABEL = {"routine": "Routine", "see_doctor_soon": "See your doctor soon",
                 "urgent": "Urgent: contact a doctor today"}
DISCLAIMER = ("This report explains your document in simple words. It is not a diagnosis "
              "or a prescription. Always follow your doctor's advice.")


# ---------------- helpers: rebuild state from the session + disk cache ----------------
def _flag_json(f: FlaggedResult) -> dict:
    d = f.to_dict()
    d["value_fmt"] = fmt_value(f)
    d["range_fmt"] = fmt_range(f)
    d["status_icon"] = STATUS_ICON.get(f.status, "⚪")
    d["status_bg"] = STATUS_BG.get(f.status, "#ffffff")
    return d


def _current_doc_and_flags():
    """Reload the extracted document + computed flags for the session's current upload."""
    img_key = session.get("img_key")
    if not img_key:
        return None, None, (None, None)
    doc = cache.load("extract", img_key, ExtractedDocument)
    if doc is None:
        return None, None, (None, None)
    profile_in = session.get("profile_in", {})
    age = profile_in.get("age") or parse_age(doc.patient_age)
    sex = profile_in.get("sex") if profile_in.get("sex") not in (None, "", "From report") \
        else (doc.patient_gender or "")
    flags = flag_all(doc.lab_results, age, sex)
    return doc, flags, (age, sex)


def _current_profile():
    profile_in = session.get("profile_in", {})
    doc, _, (age, sex) = _current_doc_and_flags()
    bmi = bmi_info(profile_in.get("weight"), profile_in.get("height"))
    return {
        "name": profile_in.get("name") or (doc.patient_name if doc else None),
        "age": age, "sex": sex,
        "weight": profile_in.get("weight") or None, "height": profile_in.get("height") or None,
        "bmi": bmi[0] if bmi else None, "bmi_cat": bmi[1] if bmi else None,
    }


def _ai_profile(profile: dict) -> dict:
    return {"Age": f"{profile['age']:g} years" if profile.get("age") else None,
            "Sex": profile.get("sex") or None,
            "Weight": f"{profile['weight']:g} kg" if profile.get("weight") else None,
            "BMI": f"{profile['bmi']} ({profile['bmi_cat']}, Asian cut-offs)" if profile.get("bmi") else None}


def _require_session():
    doc, flags, _ = _current_doc_and_flags()
    rep_key = session.get("rep_key")
    if doc is None or not rep_key:
        return None
    report = cache.load("report", rep_key, HealthReport)
    return doc, flags, report, rep_key


# ---------------- page ----------------
@app.route("/")
def index():
    return render_template("index.html")


# ---------------- analyze ----------------
@app.route("/api/analyze", methods=["POST"])
def analyze():
    upload = request.files.get("file")
    if not upload or not upload.filename:
        return jsonify(error="Please choose a file to upload."), 400

    def num(name):
        v = request.form.get(name, "").strip()
        try:
            return float(v) if v else 0
        except ValueError:
            return 0

    file_name = upload.filename
    if session.get("file_name") != file_name:
        session.clear()
        session["file_name"] = file_name

    profile_in = {
        "name": request.form.get("name", "").strip() or None,
        "age": num("age") or None,
        "sex": request.form.get("sex") or "From report",
        "weight": num("weight") or None,
        "height": num("height") or None,
    }
    session["profile_in"] = profile_in

    try:
        images = file_to_images(upload.read(), file_name)
        img_key = cache.make_key(*images)
        cache.save_images(img_key, images)
        session["img_key"] = img_key

        doc = cache.load("extract", img_key, ExtractedDocument)
        if doc is None:
            doc = extract_document(images)
            cache.save("extract", img_key, doc)

        profile = _current_profile()
        ai_profile = _ai_profile(profile)
        _, flags, _ = _current_doc_and_flags()

        rep_key = cache.make_key(doc, ai_profile)
        session["rep_key"] = rep_key

        report = cache.load("report", rep_key, HealthReport)
        if report is None:
            report = build_report(doc, flags, ai_profile)
            cache.save("report", rep_key, report)
    except Exception as e:
        return jsonify(error=f"Could not analyse the document. {e}"), 500

    return jsonify(result=_build_result_payload(doc, flags, report, rep_key, img_key, profile))


def _build_result_payload(doc, flags, report, rep_key, img_key, profile) -> dict:
    measured = [f for f in flags if f.status not in ("TEXT", "UNKNOWN")]
    abnormal = [f for f in measured if f.status in ABNORMAL]
    critical = [f.test_name for f in abnormal if f.status.startswith("CRITICAL")]
    rx = rxmod.load(rep_key)
    low_conf = ([m.name for m in doc.medicines if m.confidence < 0.6]
                + [r.test_name for r in doc.lab_results if r.confidence < 0.6])

    return {
        "rep_key": rep_key,
        "image_count": cache.image_count(img_key),
        "img_key": img_key,
        "profile_lines": profile_lines(profile, "English"),
        "document": {
            "type": doc.document_type.replace("_", " ").title(),
            "date": doc.document_date or "-",
            "doctor": doc.doctor_name or "-",
            "facility": doc.facility_name or "-",
        },
        "counts": {"checked": len(measured), "normal": len(measured) - len(abnormal),
                   "attention": len(abnormal)},
        "critical": critical,
        "flags": [_flag_json(f) for f in flags],
        "report": {
            "overall_summary": report.overall_summary,
            "normal_results": [{"test": f.test_name, "value": fmt_value(f), "range": fmt_range(f)}
                                for f in measured if f.status == "NORMAL"],
            "findings": [{
                "test_name": fnd.test_name,
                "what_it_measures": fnd.what_it_measures,
                "what_your_result_means": fnd.what_your_result_means,
                "possible_causes": fnd.possible_causes,
                "food_and_lifestyle_tips": fnd.food_and_lifestyle_tips,
                "what_your_doctor_may_do": fnd.what_your_doctor_may_do,
                "urgency": fnd.urgency, "urgency_label": URGENCY_LABEL[fnd.urgency],
                "value": next((_flag_json(f) for f in flags if f.test_name == fnd.test_name), None),
            } for fnd in report.findings],
            "diet_and_lifestyle": report.diet_and_lifestyle,
            "questions_for_doctor": report.questions_for_doctor,
            "warning_signs": report.warning_signs,
            "medicines": [m.model_dump() for m in report.medicines],
        },
        "prescription": rx.model_dump() if rx else None,
        "doctor_ok": bool(session.get("doctor_ok")),
        "low_confidence": low_conf + doc.unreadable_parts,
        "raw_document": doc.model_dump(),
    }


@app.route("/api/state")
def state():
    """Rebuild the full result payload after a page refresh, if a document is loaded."""
    bundle = _require_session()
    if bundle is None:
        return jsonify(result=None)
    doc, flags, report, rep_key = bundle
    profile = _current_profile()
    return jsonify(result=_build_result_payload(doc, flags, report, rep_key,
                                                 session["img_key"], profile))


@app.route("/api/images/<img_key>/<int:index>")
def image(img_key, index):
    path = cache.image_path(img_key, index)
    if not path:
        return "", 404
    return send_file(path, mimetype="image/jpeg")


# ---------------- doctor review ----------------
@app.route("/api/doctor/unlock", methods=["POST"])
def doctor_unlock():
    pin = (request.get_json(silent=True) or {}).get("pin", "")
    if pin == os.getenv("DOCTOR_PIN", "1234"):
        session["doctor_ok"] = True
        return jsonify(ok=True)
    return jsonify(ok=False, error="Wrong PIN."), 403


@app.route("/api/doctor/generate", methods=["POST"])
def doctor_generate():
    if not session.get("doctor_ok"):
        return jsonify(error="Doctor PIN required."), 403
    bundle = _require_session()
    if bundle is None:
        return jsonify(error="No document loaded."), 400
    doc, flags, _, rep_key = bundle
    profile = _current_profile()
    try:
        draft = rxmod.draft_treatment(doc, flags, _ai_profile(profile))
        cache.save("rxdraft", rep_key, draft)
    except Exception as e:
        return jsonify(error=f"Could not prepare suggestions: {e}"), 500
    return jsonify(draft=draft.model_dump(), rows=rxmod.draft_to_rows(draft))


@app.route("/api/doctor/state")
def doctor_state():
    if not session.get("doctor_ok"):
        return jsonify(error="Doctor PIN required."), 403
    bundle = _require_session()
    if bundle is None:
        return jsonify(error="No document loaded."), 400
    _, _, _, rep_key = bundle
    draft = cache.load("rxdraft", rep_key, rxmod.TreatmentDraft)
    rx = rxmod.load(rep_key)
    rows = ([{"Include": True, "Medicine": m.name, "Strength": m.strength, "Form": m.form,
              "Morning": m.morning, "Afternoon": m.afternoon, "Night": m.night,
              "Food": m.food, "Duration": m.duration, "Instructions": m.instructions}
             for m in rx.medicines] if rx else (rxmod.draft_to_rows(draft) if draft else []))
    return jsonify(draft=draft.model_dump() if draft else None,
                  rx=rx.model_dump() if rx else None,
                  rows=rows, food_options=rxmod.FOOD_OPTIONS)


@app.route("/api/doctor/approve", methods=["POST"])
def doctor_approve():
    if not session.get("doctor_ok"):
        return jsonify(error="Doctor PIN required."), 403
    bundle = _require_session()
    if bundle is None:
        return jsonify(error="No document loaded."), 400
    _, _, _, rep_key = bundle

    body = request.get_json(silent=True) or {}
    rows = body.get("rows", [])
    doctor_name = (body.get("doctor_name") or "").strip()
    reg_no = (body.get("registration_no") or "").strip()
    confirm = bool(body.get("confirm"))

    meds, problems = rxmod.validate_rows(rows)
    if not doctor_name or not reg_no:
        problems.append("Enter the doctor's name and registration number.")
    if not confirm:
        problems.append("Tick the confirmation box.")
    if problems:
        return jsonify(ok=False, problems=problems), 400

    tests = [t.strip() for t in (body.get("tests") or "").splitlines() if t.strip()]
    rx = rxmod.approve(doctor_name, reg_no, meds, tests,
                       body.get("advice", ""), body.get("review_after", ""))
    rxmod.save(rep_key, rx)
    return jsonify(ok=True, rx=rx.model_dump())


# ---------------- PDFs ----------------
@app.route("/api/report.pdf")
def report_pdf():
    bundle = _require_session()
    if bundle is None:
        return "No document loaded.", 400
    doc, flags, report, rep_key = bundle
    profile = _current_profile()
    rx = rxmod.load(rep_key)
    try:
        from core.pdf_report import build_pdf
        pdf_bytes = build_pdf(report, flags, profile, doc, "English", prescription=rx)
    except Exception as e:
        return f"PDF could not be created: {e}", 500
    return send_file(io.BytesIO(pdf_bytes), mimetype="application/pdf",
                     as_attachment=True, download_name="health_report.pdf")


@app.route("/api/prescription.pdf")
def prescription_pdf():
    bundle = _require_session()
    if bundle is None:
        return "No document loaded.", 400
    doc, _, _, rep_key = bundle
    profile = _current_profile()
    rx = rxmod.load(rep_key)
    if not rx:
        return "No approved prescription yet.", 400
    try:
        from core.pdf_report import build_prescription_pdf
        pdf_bytes = build_prescription_pdf(rx, profile, doc)
    except Exception as e:
        return f"Prescription PDF could not be created: {e}", 500
    return send_file(io.BytesIO(pdf_bytes), mimetype="application/pdf",
                     as_attachment=True, download_name="prescription.pdf")


if __name__ == "__main__":
    debug = os.getenv("FLASK_DEBUG", "true").lower() == "true"
    app.run(debug=debug, use_reloader=debug, port=int(os.getenv("PORT", 5000)))
