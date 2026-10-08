import streamlit as st
import pandas as pd
from core.ingest import file_to_images
from core.extract import extract_document
from core.rules import flag_all, parse_age, bmi_info
from core.analyze import build_report, ABNORMAL
from core.i18n import LABELS, fmt_range, fmt_value, profile_lines
from core.schemas import ExtractedDocument
from core.analyze import HealthReport
from core import cache
from core import prescription as rxmod
import os

st.set_page_config(page_title="Health Copilot", page_icon="🩺", layout="wide")

STATUS_ICON = {"NORMAL": "🟢", "LOW": "🔵", "HIGH": "🟠", "CRITICAL LOW": "🔴",
               "CRITICAL HIGH": "🔴", "TEXT": "⚪", "UNKNOWN": "⚪"}
STATUS_BG = {"NORMAL": "#e8f5e9", "LOW": "#e3f2fd", "HIGH": "#fff3e0",
             "CRITICAL LOW": "#ffcdd2", "CRITICAL HIGH": "#ffcdd2"}
URGENCY_KIND = {"routine": ("🟢", "info"), "see_doctor_soon": ("🟠", "warning"), "urgent": ("🔴", "error")}

# ---------------- Sidebar: patient profile ----------------
with st.sidebar:
    st.header("👤 Patient details")
    st.caption("Normal ranges depend on age and sex. Fill these for an accurate report.")
    p_name = st.text_input("Name (optional)")
    p_age = st.number_input("Age (years)", min_value=0, max_value=120, value=0,
                            help="Leave 0 to use the age printed on the report")
    p_sex = st.selectbox("Sex", ["From report", "Male", "Female"])
    p_weight = st.number_input("Weight (kg)", min_value=0.0, max_value=300.0, value=0.0, step=0.5)
    p_height = st.number_input("Height (cm)", min_value=0.0, max_value=250.0, value=0.0, step=0.5)

language = "English"          # Tamil report removed (too slow on local AI)
L = LABELS[language]

st.title("🩺 Personal Health Copilot")
st.caption("Upload a lab report, prescription or discharge summary and get a simple, detailed explanation.")
st.info("⚕️ This tool explains your records in simple words. It does **not** diagnose or prescribe. "
        "Always confirm with your doctor before changing any treatment.")

def doctor_review(doc, flags, profile, rep_key, rx):
    """Only the doctor sees AI suggestions. Nothing reaches the patient until approved."""
    st.subheader("🩺 Doctor review & approval")
    if not st.session_state.get("doctor_ok"):
        st.caption("For the treating doctor only. AI treatment suggestions are shown here and "
                   "are never shown to the patient until a doctor approves them.")
        pin = st.text_input("Doctor PIN", type="password", key="doctor_pin")
        if st.button("Unlock"):
            if pin == os.getenv("DOCTOR_PIN", "1234"):
                st.session_state["doctor_ok"] = True
                st.rerun()
            else:
                st.error("Wrong PIN.")
        return

    if rx:
        st.success(f"Approved by Dr. {rx.doctor_name} on {rx.approved_at}. "
                   "Editing below and approving again will replace it.".replace("Dr. Dr.", "Dr."))

    draft_key = f"draft_{rep_key}"
    if draft_key not in st.session_state:
        st.session_state[draft_key] = cache.load("rxdraft", rep_key, rxmod.TreatmentDraft)
    draft = st.session_state[draft_key]

    if st.button("🤖 Generate AI treatment suggestions", disabled=draft is not None):
        try:
            with st.spinner("Preparing suggestions for the doctor..."):
                draft = rxmod.draft_treatment(doc, flags, st.session_state.get("ai_profile", {}))
            cache.save("rxdraft", rep_key, draft)
            st.session_state[draft_key] = draft
            st.session_state.pop(f"rows_{rep_key}", None)
            st.rerun()
        except Exception as e:
            st.error(f"Could not prepare suggestions: {e}")

    if draft:
        st.warning("⚠️ AI draft for clinical review only. Verify every suggestion against the "
                   "patient's history, allergies, current medicines and the original report.")
        st.markdown(f"**AI clinical note:** {draft.clinical_note}")
        if draft.referral_or_urgent_action:
            st.error(f"**Urgent / referral:** {draft.referral_or_urgent_action}")
        for m in draft.medicines:
            with st.expander(f"💡 {m.generic_name} — {m.purpose}"):
                st.markdown(f"**Related results:** {', '.join(m.related_tests)}")
                st.markdown("**Cautions:**\n" + "\n".join(f"- {c}" for c in m.cautions))

    # ---- editable prescription table ----
    st.markdown("#### ✍️ Prescription")
    st.caption("Edit freely: untick Include to drop a suggestion, add rows with ＋. "
               "Strength and duration must be filled by the doctor.")
    rows_key = f"rows_{rep_key}"
    if rows_key not in st.session_state:
        if rx:
            st.session_state[rows_key] = [{
                "Include": True, "Medicine": m.name, "Strength": m.strength, "Form": m.form,
                "Morning": m.morning, "Afternoon": m.afternoon, "Night": m.night,
                "Food": m.food, "Duration": m.duration, "Instructions": m.instructions}
                for m in rx.medicines]
        else:
            st.session_state[rows_key] = rxmod.draft_to_rows(draft) if draft else []
    base = pd.DataFrame(st.session_state[rows_key], columns=[
        "Include", "Medicine", "Strength", "Form", "Morning", "Afternoon", "Night",
        "Food", "Duration", "Instructions"])
    edited = st.data_editor(
        base, num_rows="dynamic", use_container_width=True, hide_index=True,
        key=f"editor_{rep_key}",
        column_config={
            "Include": st.column_config.CheckboxColumn(default=True, width="small"),
            "Medicine": st.column_config.TextColumn(required=True, width="medium"),
            "Strength": st.column_config.TextColumn(help="e.g. 100 mg, 5 ml", width="small"),
            "Form": st.column_config.SelectboxColumn(
                options=["Tablet", "Capsule", "Syrup", "Injection", "Drops", "Ointment", "Sachet"],
                default="Tablet", width="small"),
            "Morning": st.column_config.CheckboxColumn(default=False, width="small"),
            "Afternoon": st.column_config.CheckboxColumn(default=False, width="small"),
            "Night": st.column_config.CheckboxColumn(default=False, width="small"),
            "Food": st.column_config.SelectboxColumn(options=rxmod.FOOD_OPTIONS,
                                                     default="After food", width="small"),
            "Duration": st.column_config.TextColumn(help="e.g. 30 days", width="small"),
            "Instructions": st.column_config.TextColumn(width="medium"),
        })

    default_tests = "\n".join(draft.tests_to_consider) if draft else ""
    tests = st.text_area("Tests advised (one per line)",
                         value="\n".join(rx.tests) if rx else default_tests, key=f"tests_{rep_key}")
    advice = st.text_area("Advice for the patient",
                          value=rx.advice if rx else ("\n".join(draft.lifestyle_advice) if draft else ""),
                          key=f"advice_{rep_key}")
    review_after = st.text_input("Review / follow-up", value=rx.review_after if rx else "",
                                 placeholder="e.g. Review with repeat CBC after 4 weeks",
                                 key=f"review_{rep_key}")

    c1, c2 = st.columns(2)
    doc_name = c1.text_input("Doctor name", value=rx.doctor_name if rx else "", key=f"dname_{rep_key}")
    reg_no = c2.text_input("Registration No.", value=rx.registration_no if rx else "",
                           key=f"dreg_{rep_key}")
    confirm = st.checkbox("I have reviewed this patient's report and take clinical responsibility "
                          "for this prescription.", key=f"confirm_{rep_key}")

    if st.button("✅ Approve & send to patient", type="primary"):
        meds, problems = rxmod.validate_rows(edited.fillna("").to_dict("records"))
        if not doc_name.strip() or not reg_no.strip():
            problems.append("Enter the doctor's name and registration number.")
        if not confirm:
            problems.append("Tick the confirmation box.")
        if problems:
            st.error("Please fix before approving:\n" + "\n".join(f"- {p}" for p in problems))
        else:
            new_rx = rxmod.approve(doc_name, reg_no, meds,
                                   [t.strip() for t in tests.splitlines() if t.strip()],
                                   advice, review_after)
            rxmod.save(rep_key, new_rx)
            st.session_state[rows_key] = edited.fillna("").to_dict("records")
            st.success("Approved. The patient can now see it in the Medicines tab and in the PDF.")
            st.rerun()


uploaded = st.file_uploader("Upload a document", type=["jpg", "jpeg", "png", "pdf"])

if uploaded:
    if st.session_state.get("file_name") != uploaded.name:
        st.session_state.clear()
        st.session_state["file_name"] = uploaded.name
    images = file_to_images(uploaded.getvalue(), uploaded.name)

    left, right = st.columns([2, 3])
    with left:
        st.subheader("📄 Your document")
        for img in images:
            st.image(img, use_container_width=True)

    with right:
        if st.button("🔍 Analyse document", type="primary", use_container_width=True):
            try:
                img_key = cache.make_key(*images)
                doc = cache.load("extract", img_key, ExtractedDocument)
                if doc is None:
                    with st.spinner("Step 1/2: Reading your document..."):
                        doc = extract_document(images)
                    cache.save("extract", img_key, doc)

                age = p_age if p_age > 0 else parse_age(doc.patient_age)
                sex = p_sex if p_sex != "From report" else (doc.patient_gender or "")
                flags = flag_all(doc.lab_results, age, sex)
                bmi = bmi_info(p_weight, p_height)
                profile = {"name": p_name or doc.patient_name, "age": age, "sex": sex,
                           "weight": p_weight or None, "height": p_height or None,
                           "bmi": bmi[0] if bmi else None, "bmi_cat": bmi[1] if bmi else None}
                ai_profile = {"Age": f"{age:g} years" if age else None, "Sex": sex or None,
                              "Weight": f"{p_weight:g} kg" if p_weight else None,
                              "BMI": f"{bmi[0]} ({bmi[1]}, Asian cut-offs)" if bmi else None}

                rep_key = cache.make_key(doc, ai_profile)
                report_en = cache.load("report", rep_key, HealthReport)
                if report_en is None:
                    with st.spinner("Step 2/2: Writing your simple report..."):
                        report_en = build_report(doc, flags, ai_profile)
                    cache.save("report", rep_key, report_en)

                st.session_state.update(doc=doc, flags=flags, profile=profile, rep_key=rep_key,
                                        ai_profile=ai_profile, reports={"English": report_en},
                                        pdfs={})
            except Exception as e:
                st.error(f"Could not analyse the document. {e}")
                st.stop()

        if "reports" in st.session_state:
            doc = st.session_state["doc"]
            flags = st.session_state["flags"]
            profile = st.session_state["profile"]
            reports = st.session_state["reports"]

            report = reports["English"]
            rep_key = st.session_state["rep_key"]
            rx = rxmod.load(rep_key)              # doctor-approved prescription (or None)

            # ---- header ----
            st.markdown("  ·  ".join(f"**{k}:** {v}" for k, v in profile_lines(profile, language)))
            st.caption(f"{L['document']}: {doc.document_type.replace('_', ' ').title()} · "
                       f"{L['date']}: {doc.document_date or '-'} · {L['doctor']}: {doc.doctor_name or '-'} · "
                       f"{L['lab']}: {doc.facility_name or '-'}")

            measured = [f for f in flags if f.status not in ("TEXT", "UNKNOWN")]
            abnormal = [f for f in measured if f.status in ABNORMAL]
            critical = [f.test_name for f in abnormal if f.status.startswith("CRITICAL")]
            c1, c2, c3 = st.columns(3)
            c1.metric(L["tests_checked"], len(measured))
            c2.metric(L["normal"], len(measured) - len(abnormal))
            c3.metric(L["need_attention"], len(abnormal))
            if critical:
                st.error("🔴 " + L["critical_alert"].format(tests=", ".join(critical)))

            # ---- PDF download ----
            pdfs = st.session_state["pdfs"]
            pdf_key = f"report_{rx.approved_at if rx else 'none'}"
            pdf_error = None
            if pdf_key not in pdfs:
                try:
                    from core.pdf_report import build_pdf
                    pdfs[pdf_key] = build_pdf(report, flags, profile, doc, language, prescription=rx)
                except Exception as e:
                    pdf_error = e          # not cached, so it retries after you fix it

            def pdf_button(key):
                if pdf_key in pdfs:
                    st.download_button(L["download_pdf"], pdfs[pdf_key], type="primary",
                                       file_name="health_report.pdf", mime="application/pdf",
                                       use_container_width=True, key=key)
                else:
                    st.error(f"PDF could not be created: {pdf_error}. "
                             "Run 'pip install reportlab' in the terminal and restart the app.")

            pdf_button("pdf_top")

            tab1, tab2, tab3, tab5, tab4 = st.tabs([L["tab_report"], L["tab_tests"], L["tab_meds"],
                                                    "🩺 Doctor review", L["tab_data"]])

            with tab1:
                st.subheader(L["summary"])
                st.write(report.overall_summary)

                normal = [f for f in measured if f.status == "NORMAL"]
                if normal:
                    st.success(f"**✅ {L['normal_results']}**\n\n" + "\n".join(
                        "- " + L["normal_line"].format(test=f.test_name, value=fmt_value(f), range=fmt_range(f))
                        for f in normal))

                if report.findings:
                    st.subheader("⚠️ " + L["needs_attention"])
                    by_name = {f.test_name: f for f in flags}
                    for fnd in report.findings:
                        icon, kind = URGENCY_KIND.get(fnd.urgency, URGENCY_KIND["routine"])
                        with st.expander(f"{fnd.test_name}  ·  {icon} {L['urgency'][fnd.urgency]}", expanded=True):
                            f = by_name.get(fnd.test_name)
                            if f:
                                st.markdown("**" + L["your_value_line"].format(
                                    value=fmt_value(f), range=fmt_range(f),
                                    status=f"{STATUS_ICON[f.status]} {L['status_names'][f.status]}") + "**")
                            getattr(st, kind)(fnd.what_your_result_means)
                            st.markdown(f"**{L['what_measures']}:** {fnd.what_it_measures}")
                            a, b = st.columns(2)
                            a.markdown(f"**{L['possible_causes']}**\n" + "\n".join(f"- {x}" for x in fnd.possible_causes))
                            b.markdown(f"**{L['food_tips']}**\n" + "\n".join(f"- {x}" for x in fnd.food_and_lifestyle_tips))
                            st.markdown(f"**{L['doctor_may']}**\n" + "\n".join(f"- {x}" for x in fnd.what_your_doctor_may_do))

                for title, items in [("🥗 " + L["diet"], report.diet_and_lifestyle),
                                     ("❓ " + L["questions"], report.questions_for_doctor)]:
                    if items:
                        st.subheader(title)
                        st.markdown("\n".join(f"- {i}" for i in items))
                if report.warning_signs:
                    st.warning(f"**🚨 {L['warning']}:**\n" + "\n".join(f"- {w}" for w in report.warning_signs))

            with tab2:
                rows = [{L["status"]: f"{STATUS_ICON[f.status]} {L['status_names'][f.status]}",
                         L["test"]: f.test_name, L["your_value"]: fmt_value(f),
                         L["normal_range"]: fmt_range(f), L["note"]: f.note, "_s": f.status}
                        for f in flags]
                if rows:
                    df = pd.DataFrame(rows)
                    colors = [STATUS_BG.get(s, "#ffffff") for s in df["_s"]]
                    df = df.drop(columns="_s")
                    styled = df.style.apply(
                        lambda r: [f"background-color: {colors[r.name]}"] * len(r), axis=1)
                    st.dataframe(styled, use_container_width=True, hide_index=True)
                else:
                    st.write("-")

            with tab3:
                st.subheader("✅ Doctor-approved prescription")
                if rx:
                    st.dataframe(pd.DataFrame([{
                        "Medicine": f"{m.name} {m.strength}", "Form": m.form,
                        "Morning-Afternoon-Night": f"{m.pattern}  ({m.when})", "Food": m.food,
                        "Duration": m.duration, "Instructions": m.instructions} for m in rx.medicines]),
                        use_container_width=True, hide_index=True)
                    if rx.tests:
                        st.markdown("**Tests advised:** " + ", ".join(rx.tests))
                    if rx.advice:
                        st.markdown(f"**Doctor's advice:** {rx.advice}")
                    if rx.review_after:
                        st.markdown(f"**Review:** {rx.review_after}")
                    st.caption(f"Approved by Dr. {rx.doctor_name} (Reg. No. {rx.registration_no}) "
                               f"on {rx.approved_at}".replace("Dr. Dr.", "Dr."))
                    try:
                        from core.pdf_report import build_prescription_pdf
                        st.download_button("⬇️ Download prescription (PDF)",
                                           build_prescription_pdf(rx, profile, doc),
                                           file_name="prescription.pdf", mime="application/pdf",
                                           key="rx_pdf_patient")
                    except Exception as e:
                        st.error(f"Prescription PDF could not be created: {e}")
                else:
                    st.info("⏳ No doctor-approved prescription yet. Medicines are shown here only "
                            "after a doctor reviews this report and approves them.")

                st.divider()
                st.subheader("💊 Medicines written on the uploaded document")
                if report.medicines:
                    for m in report.medicines:
                        with st.expander(f"💊 {m.name}", expanded=True):
                            st.markdown(f"**{L['used_for']}:** {m.used_for}")
                            st.markdown(f"**{L['how_to_take']}:** {m.how_to_take}")
                            st.markdown(f"**{L['side_effects']}:** " + ", ".join(m.common_side_effects))
                            st.markdown(f"**{L['precautions']}:** " + "; ".join(m.precautions))
                    st.caption(L["meds_caution"])
                else:
                    st.write(L["no_meds"])

            with tab5:
                doctor_review(doc, flags, profile, rep_key, rx)

            with tab4:
                low_conf = ([m.name for m in doc.medicines if m.confidence < 0.6]
                            + [r.test_name for r in doc.lab_results if r.confidence < 0.6])
                if low_conf or doc.unreadable_parts:
                    st.warning("Please check these against the original: "
                               + ", ".join(low_conf + doc.unreadable_parts))
                st.json(doc.model_dump())

            st.caption("⚕️ " + L["disclaimer"])
            st.divider()
            pdf_button("pdf_bottom")