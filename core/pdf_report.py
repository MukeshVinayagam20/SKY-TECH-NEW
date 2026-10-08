"""Build a downloadable PDF of the health report (English).

Needs:  pip install reportlab
"""
from datetime import date
from io import BytesIO
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (KeepTogether, Paragraph,
                                SimpleDocTemplate, Spacer, Table, TableStyle)

from .i18n import LABELS, fmt_range, fmt_value, profile_lines

TEAL = colors.HexColor("#0d6e6e")
DARK = colors.HexColor("#212529")
GREY = colors.HexColor("#6c757d")
LINE = colors.HexColor("#d0d7de")
STATUS_FILL = {
    "NORMAL": colors.HexColor("#e8f5e9"), "LOW": colors.HexColor("#e3f2fd"),
    "HIGH": colors.HexColor("#fff3e0"), "CRITICAL LOW": colors.HexColor("#ffcdd2"),
    "CRITICAL HIGH": colors.HexColor("#ffcdd2"),
}
STATUS_TEXT = {
    "NORMAL": colors.HexColor("#1b5e20"), "LOW": colors.HexColor("#0d47a1"),
    "HIGH": colors.HexColor("#e65100"), "CRITICAL LOW": colors.HexColor("#b71c1c"),
    "CRITICAL HIGH": colors.HexColor("#b71c1c"),
}
URGENCY_FILL = {"routine": colors.HexColor("#e8f5e9"),
                "see_doctor_soon": colors.HexColor("#fff3e0"),
                "urgent": colors.HexColor("#ffcdd2")}

S = {
    "body": ParagraphStyle("body", fontName="Helvetica", fontSize=10, leading=14, textColor=DARK),
    "small": ParagraphStyle("small", fontName="Helvetica", fontSize=8.5, leading=11.5, textColor=DARK),
    "muted": ParagraphStyle("muted", fontName="Helvetica", fontSize=9.5, leading=13, textColor=GREY),
    "label": ParagraphStyle("label", fontName="Helvetica-Bold", fontSize=10, leading=14,
                            textColor=DARK, spaceBefore=4),
    "h1": ParagraphStyle("h1", fontName="Helvetica-Bold", fontSize=19, leading=23,
                         textColor=colors.white),
    "h1sub": ParagraphStyle("h1sub", fontName="Helvetica", fontSize=9.5, leading=12,
                            textColor=colors.HexColor("#cfe8e8")),
    "h2": ParagraphStyle("h2", fontName="Helvetica-Bold", fontSize=13.5, leading=17,
                         textColor=TEAL, spaceBefore=12, spaceAfter=4),
    "h3": ParagraphStyle("h3", fontName="Helvetica-Bold", fontSize=11, leading=14, textColor=DARK),
    "value": ParagraphStyle("value", fontName="Helvetica-Bold", fontSize=9.5, leading=13,
                            textColor=TEAL),
    "cell": ParagraphStyle("cell", fontName="Helvetica", fontSize=9, leading=11.5, textColor=DARK),
    "cellb": ParagraphStyle("cellb", fontName="Helvetica-Bold", fontSize=9, leading=11.5,
                            textColor=DARK),
    "head": ParagraphStyle("head", fontName="Helvetica-Bold", fontSize=9, leading=11.5,
                           textColor=colors.white),
}


def _clean(text) -> str:
    # built-in PDF fonts can't draw a few symbols, so swap them for safe ones
    return (str(text).replace("µ", "u").replace("–", "-").replace("—", "-")
            .replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"'))


def _p(text, style="body"):
    return Paragraph(escape(_clean(text)), S[style] if isinstance(style, str) else style)


def _bullets(items, style="body"):
    base = S[style]
    bstyle = ParagraphStyle(f"b_{style}", parent=base, leftIndent=14, bulletIndent=3,
                            spaceAfter=1.5, bulletColor=TEAL, bulletFontName="Helvetica-Bold")
    # returns a plain list of paragraphs (safe inside tables and KeepTogether)
    return [Paragraph(escape(_clean(i)), bstyle, bulletText="\u2022") for i in items]


def _box(flowables, fill, pad=7):
    t = Table([[flowables]], colWidths=["100%"])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), fill),
        ("LEFTPADDING", (0, 0), (-1, -1), pad), ("RIGHTPADDING", (0, 0), (-1, -1), pad),
        ("TOPPADDING", (0, 0), (-1, -1), pad - 1), ("BOTTOMPADDING", (0, 0), (-1, -1), pad),
    ]))
    return t


def _h2(text):
    return [_p(text, "h2"),
            Table([[""]], colWidths=["100%"], rowHeights=[1.2],
                  style=[("LINEABOVE", (0, 0), (-1, -1), 1.2, TEAL)]),
            Spacer(1, 4)]


def _footer(canvas, doc_tpl, text):
    canvas.saveState()
    canvas.setFont("Helvetica", 7.5)
    canvas.setFillColor(GREY)
    canvas.drawCentredString(A4[0] / 2, 10 * mm, f"{text}   |   Page {doc_tpl.page}")
    canvas.restoreState()


def build_pdf(report, flags, profile: dict, doc, language: str = "English",
              prescription=None) -> bytes:
    L = LABELS["English"]
    buf = BytesIO()
    tpl = SimpleDocTemplate(buf, pagesize=A4, leftMargin=16 * mm, rightMargin=16 * mm,
                            topMargin=14 * mm, bottomMargin=18 * mm,
                            title=L["report_title"], author="Personal Health Copilot")
    width = A4[0] - 32 * mm
    story = []

    # ---- header band ----
    header = Table([[_p(L["report_title"], "h1")], [_p("Personal Health Copilot  ·  "
                    "AI explanation of your medical document", "h1sub")]], colWidths=[width])
    header.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), TEAL),
        ("LEFTPADDING", (0, 0), (-1, -1), 10), ("TOPPADDING", (0, 0), (0, 0), 10),
        ("BOTTOMPADDING", (0, -1), (-1, -1), 10),
    ]))
    story += [header, Spacer(1, 8)]

    # ---- patient + document info (2 columns) ----
    info = profile_lines(profile, "English")
    info += [(L["document"], doc.document_type.replace("_", " ").title()),
             (L["date"], doc.document_date or "-"),
             (L["doctor"], doc.doctor_name or "-"),
             (L["lab"], doc.facility_name or "-")]
    cells = [[_p(k, "cellb"), _p(v, "cell")] for k, v in info]
    if len(cells) % 2:
        cells.append(["", ""])
    rows = [cells[i] + cells[i + 1] for i in range(0, len(cells), 2)]
    info_t = Table(rows, colWidths=[width * 0.14, width * 0.36, width * 0.14, width * 0.36])
    info_t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 0), (-1, -1), 0.4, LINE),
        ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    story += [info_t, Spacer(1, 8)]
    story.append(_box([_p(L["disclaimer"], "small")], colors.HexColor("#fff8e1")))

    # ---- at a glance ----
    measured = [f for f in flags if f.status not in ("TEXT", "UNKNOWN")]
    abnormal = [f for f in measured if f.status != "NORMAL"]
    critical = [f.test_name for f in abnormal if f.status.startswith("CRITICAL")]
    stat_style = ParagraphStyle("stat", parent=S["h3"], alignment=TA_CENTER, fontSize=16, leading=19)
    lab_style = ParagraphStyle("statl", parent=S["muted"], alignment=TA_CENTER, fontSize=8.5)
    glance = Table([[Paragraph(str(len(measured)), stat_style),
                     Paragraph(str(len(measured) - len(abnormal)), stat_style),
                     Paragraph(str(len(abnormal)), stat_style)],
                    [Paragraph(L["tests_checked"], lab_style), Paragraph(L["normal"], lab_style),
                     Paragraph(L["need_attention"], lab_style)]],
                   colWidths=[width / 3] * 3)
    glance.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f1f3f5")),
        ("BACKGROUND", (1, 0), (1, -1), STATUS_FILL["NORMAL"]),
        ("BACKGROUND", (2, 0), (2, -1), STATUS_FILL["HIGH"] if abnormal else STATUS_FILL["NORMAL"]),
        ("LINEAFTER", (0, 0), (1, -1), 2, colors.white),
        ("TOPPADDING", (0, 0), (-1, 0), 8), ("BOTTOMPADDING", (0, -1), (-1, -1), 8),
    ]))
    story += [Spacer(1, 8), glance]
    if critical:
        story += [Spacer(1, 6), _box([Paragraph(
            "<b>" + escape(_clean(L["critical_alert"].format(tests=", ".join(critical)))) + "</b>",
            S["body"])], STATUS_FILL["CRITICAL HIGH"])]

    # ---- summary ----
    story += _h2(L["summary"]) + [_p(report.overall_summary)]

    # ---- test results table ----
    if flags:
        story += _h2(L["test_results"])
        data = [[_p(h, "head") for h in (L["test"], L["your_value"], L["normal_range"], L["status"])]]
        style = [
            ("BACKGROUND", (0, 0), (-1, 0), TEAL),
            ("GRID", (0, 0), (-1, -1), 0.4, LINE),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]
        for r, f in enumerate(flags, start=1):
            status_p = Paragraph(f"<b>{escape(L['status_names'].get(f.status, f.status))}</b>",
                                 ParagraphStyle("st", parent=S["cell"],
                                                textColor=STATUS_TEXT.get(f.status, DARK)))
            data.append([_p(f.test_name, "cell"), _p(fmt_value(f), "cell"),
                         _p(fmt_range(f), "cell"), status_p])
            if f.status in STATUS_FILL and f.status != "NORMAL":
                style.append(("BACKGROUND", (0, r), (-1, r), STATUS_FILL[f.status]))
        table = Table(data, colWidths=[width * 0.32, width * 0.22, width * 0.28, width * 0.18],
                      repeatRows=1)
        table.setStyle(TableStyle(style))
        story.append(table)

        notes = [f"{f.test_name}: {f.note}" for f in flags if f.note and f.status in STATUS_FILL]
        if notes:
            story += [Spacer(1, 5), _p(L["note"], "label")] + _bullets(notes, "small")

    # ---- normal results ----
    normal = [f for f in measured if f.status == "NORMAL"]
    if normal:
        story += _h2(L["normal_results"])
        story.extend(_bullets([L["normal_line"].format(test=f.test_name, value=fmt_value(f),
                                                       range=fmt_range(f)) for f in normal]))

    # ---- findings ----
    if report.findings:
        story += _h2(L["needs_attention"])
        by_name = {f.test_name: f for f in flags}
        for fnd in report.findings:
            f = by_name.get(fnd.test_name)
            head = _box([_p(f"{fnd.test_name}   ·   {L['urgency'].get(fnd.urgency, fnd.urgency)}", "h3")],
                        URGENCY_FILL.get(fnd.urgency, colors.HexColor("#f1f3f5")), pad=6)
            block = [head, Spacer(1, 4)]
            if f:
                block.append(_p(L["your_value_line"].format(
                    value=fmt_value(f), range=fmt_range(f),
                    status=L["status_names"].get(f.status, f.status)), "value"))
            block += [Spacer(1, 3), _p(fnd.what_your_result_means), Spacer(1, 3),
                      _p(f"{L['what_measures']}: {fnd.what_it_measures}", "muted")]
            story.append(KeepTogether(block))
            for label, items in [(L["possible_causes"], fnd.possible_causes),
                                 (L["food_tips"], fnd.food_and_lifestyle_tips),
                                 (L["doctor_may"], fnd.what_your_doctor_may_do)]:
                if items:
                    story.append(KeepTogether([_p(label, "label")] + _bullets(items)))
            story.append(Spacer(1, 10))

    # ---- medicines ----
    if report.medicines:
        story += _h2(L["medicines"])
        for m in report.medicines:
            block = [_p(m.name, "h3"), _p(f"{L['used_for']}: {m.used_for}"),
                     _p(f"{L['how_to_take']}: {m.how_to_take}")]
            if m.common_side_effects:
                block += [_p(L["side_effects"], "label")] + _bullets(m.common_side_effects)
            if m.precautions:
                block += [_p(L["precautions"], "label")] + _bullets(m.precautions)
            story += [KeepTogether(block), Spacer(1, 8)]
        story.append(_box([_p(L["meds_caution"], "small")], colors.HexColor("#fff8e1")))

    # ---- tips, questions, warnings ----
    for title, items in [(L["diet"], report.diet_and_lifestyle),
                         (L["questions"], report.questions_for_doctor)]:
        if items:
            story += _h2(title) + _bullets(items)
    if report.warning_signs:
        story += _h2(L["warning"]) + [_box(_bullets(report.warning_signs),
                                           colors.HexColor("#ffebee"))]

    # ---- doctor-approved prescription (only after approval) ----
    if prescription is not None:
        story += _h2("Doctor-approved prescription") + _rx_flowables(prescription, width)

    story += [Spacer(1, 14), _box([_p(L["disclaimer"], "small")], colors.HexColor("#f1f3f5"))]

    footer_text = f"{L['generated']}  ·  {date.today():%d-%m-%Y}"
    tpl.build(story, onFirstPage=lambda c, d: _footer(c, d, footer_text),
              onLaterPages=lambda c, d: _footer(c, d, footer_text))
    return buf.getvalue()


# =====================================================================
#  Prescription (after doctor approval)
# =====================================================================
def _rx_flowables(rx, width):
    out = []
    head = [_p(h, "head") for h in ("#", "Medicine", "Morning / Afternoon / Night",
                                    "Food", "Duration")]
    data, style = [head], [
        ("BACKGROUND", (0, 0), (-1, 0), TEAL),
        ("GRID", (0, 0), (-1, -1), 0.4, LINE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]
    for i, m in enumerate(rx.medicines, start=1):
        name = Paragraph(f"<b>{escape(_clean(m.name))}</b> {escape(_clean(m.strength))}"
                         f"<br/><font color='#6c757d' size='8.5'>{escape(_clean(m.form))}"
                         + (f" · {escape(_clean(m.instructions))}" if m.instructions else "")
                         + "</font>", S["cell"])
        when = Paragraph(f"<b>{m.pattern}</b><br/><font size='8.5'>{escape(m.when)}</font>",
                         S["cell"])
        data.append([_p(str(i), "cell"), name, when, _p(m.food, "cell"), _p(m.duration, "cell")])
        if i % 2 == 0:
            style.append(("BACKGROUND", (0, i), (-1, i), colors.HexColor("#f6f8fa")))
    if rx.medicines:
        t = Table(data, colWidths=[width * 0.06, width * 0.40, width * 0.22, width * 0.16,
                                   width * 0.16], repeatRows=1)
        t.setStyle(TableStyle(style))
        out += [t, Spacer(1, 4),
                _p("1-0-1 means: 1 in the morning, 0 in the afternoon, 1 at night.", "muted")]
    else:
        out.append(_p("No medicines prescribed."))
    if rx.tests:
        out += [_p("Tests advised", "label")] + _bullets(rx.tests)
    if rx.advice:
        out += [_p("Doctor's advice", "label"), _p(rx.advice)]
    if rx.review_after:
        out += [_p("Review / follow-up", "label"), _p(rx.review_after)]
    sign = Table([[_p("Approved by", "muted"), _p("Registration No.", "muted"),
                   _p("Approved on", "muted")],
                  [_p(f"Dr. {rx.doctor_name}".replace("Dr. Dr.", "Dr."), "h3"),
                   _p(rx.registration_no, "h3"), _p(rx.approved_at, "h3")]],
                 colWidths=[width * 0.4, width * 0.3, width * 0.3])
    sign.setStyle(TableStyle([("LINEABOVE", (0, 0), (-1, 0), 1, TEAL),
                              ("TOPPADDING", (0, 0), (-1, -1), 4)]))
    out += [Spacer(1, 10), KeepTogether([sign])]
    return out


def build_prescription_pdf(rx, profile: dict, doc) -> bytes:
    buf = BytesIO()
    tpl = SimpleDocTemplate(buf, pagesize=A4, leftMargin=16 * mm, rightMargin=16 * mm,
                            topMargin=14 * mm, bottomMargin=18 * mm,
                            title="Prescription", author=rx.doctor_name)
    width = A4[0] - 32 * mm
    header = Table([[_p("Prescription", "h1")],
                    [_p("Reviewed and approved by a registered doctor  ·  Personal Health Copilot",
                        "h1sub")]], colWidths=[width])
    header.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), TEAL),
        ("LEFTPADDING", (0, 0), (-1, -1), 10), ("TOPPADDING", (0, 0), (0, 0), 10),
        ("BOTTOMPADDING", (0, -1), (-1, -1), 10),
    ]))
    info = profile_lines(profile, "English") + [("Based on", f"{doc.document_type.replace('_', ' ').title()}"
                                                 f" dated {doc.document_date or '-'}")]
    cells = [[_p(k, "cellb"), _p(v, "cell")] for k, v in info]
    if len(cells) % 2:
        cells.append(["", ""])
    rows = [cells[i] + cells[i + 1] for i in range(0, len(cells), 2)]
    info_t = Table(rows, colWidths=[width * 0.14, width * 0.36, width * 0.14, width * 0.36])
    info_t.setStyle(TableStyle([("LINEBELOW", (0, 0), (-1, -1), 0.4, LINE),
                                ("TOPPADDING", (0, 0), (-1, -1), 3),
                                ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))
    story = [header, Spacer(1, 8), info_t, Spacer(1, 14),
             Paragraph("<font size='22' color='#0d6e6e'><b>Rx</b></font>", S["body"]), Spacer(1, 10)]
    story += _rx_flowables(rx, width)
    story += [Spacer(1, 14), _box([_p("Take medicines exactly as written above. Do not change the dose "
                                      "or stop early without asking your doctor. Contact your doctor "
                                      "if you get side effects.", "small")],
                                  colors.HexColor("#fff8e1"))]
    footer_text = f"Prescription approved {rx.approved_at}  ·  Personal Health Copilot"
    tpl.build(story, onFirstPage=lambda c, d: _footer(c, d, footer_text),
              onLaterPages=lambda c, d: _footer(c, d, footer_text))
    return buf.getvalue()