"""
pdf_writers.py
==============
PDF writers for each document layout using reportlab.
Produces standard-compliant PDFs compatible with PyMuPDF search_for().

Replaces fpdf2 which produced non-standard internal text encoding that
broke PyMuPDF bounding-box lookups during redaction testing.
"""

from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
)
from reportlab.platypus.flowables import HRFlowable

from .layout_renderers import (
    render_plain_note, render_table_note, render_discharge_summary,
    render_footer_note, render_referral_letter, render_lab_result_email,
)

PAGE_W, PAGE_H = letter
MARGIN = 0.75 * inch


# ─────────────────────────────────────────────
# SHARED STYLE HELPERS
# ─────────────────────────────────────────────

def _s(name, font="Helvetica", size=9, bold=False, mono=False, leading=13,
        alignment=0, space_after=0, color=colors.black):
    """Convenience factory for ParagraphStyle."""
    if mono:
        font = "Courier"
    elif bold:
        font = "Helvetica-Bold"
    return ParagraphStyle(
        name,
        fontName=font,
        fontSize=size,
        leading=leading,
        alignment=alignment,
        spaceAfter=space_after,
        textColor=color,
    )


def _safe(text: str) -> str:
    """Escape XML special chars so Paragraph doesn't choke."""
    return (str(text)
            .replace('&', '&amp;')
            .replace('<', '&lt;')
            .replace('>', '&gt;'))


def _doc(path, top=MARGIN, bottom=MARGIN):
    return SimpleDocTemplate(
        path, pagesize=letter,
        leftMargin=MARGIN, rightMargin=MARGIN,
        topMargin=top, bottomMargin=bottom,
    )


# ─────────────────────────────────────────────
# LAYOUT 1 — PLAIN SOAP NOTE
# ─────────────────────────────────────────────

def write_pdf_plain(phi, path):
    """Plain SOAP note — monospace paragraph layout."""
    mono   = _s("mono", mono=True)
    mono_b = _s("mono_b", mono=True, bold=False)  # section headers still mono

    doc = _doc(path)
    story = []

    for line in render_plain_note(phi).split("\n"):
        if line.startswith("="):
            story.append(HRFlowable(width="100%", thickness=1, color=colors.black))
            story.append(Spacer(1, 2))
        elif not line.strip():
            story.append(Spacer(1, 5))
        else:
            story.append(Paragraph(_safe(line), mono))

    doc.build(story)


# ─────────────────────────────────────────────
# LAYOUT 2 — TABLE LAB REPORT
# ─────────────────────────────────────────────

def write_pdf_table_labs(phi, path):
    """Table-structured lab report — PHI in table cells."""
    lbl   = _s("lbl",   bold=True)
    val   = _s("val")
    title = _s("title", bold=True, size=14, alignment=1, space_after=2)
    sub   = _s("sub",   bold=True, size=11, alignment=1, space_after=4)
    small = _s("small", size=8)
    lhead = _s("lhead", bold=True)

    doc = _doc(path)
    story = []

    story.append(Paragraph(_safe(phi["facility"]), title))
    story.append(Paragraph("LABORATORY REPORT", sub))
    story.append(Spacer(1, 8))

    # Patient info table — 4 columns (label | value | label | value)
    avail = PAGE_W - 2 * MARGIN
    cw = [avail * 0.16, avail * 0.34, avail * 0.16, avail * 0.34]

    info_rows = [
        ("Patient Name:", phi["patient_name"],   "MRN:",          phi["mrn"]),
        ("Date of Birth:", phi["dob"],            "SSN:",          phi["ssn"]),
        ("Provider:",      phi["provider_name"],  "Visit Date:",   phi["visit_date"]),
        ("Phone:",         phi["phone"],          "Email:",        phi["email"]),
        ("Insurance ID:",  phi["insurance_id"],   "Portal:",       phi["portal_url"]),
    ]
    table_data = [
        [Paragraph(_safe(a), lbl), Paragraph(_safe(b), val),
         Paragraph(_safe(c), lbl), Paragraph(_safe(d), val)]
        for a, b, c, d in info_rows
    ]
    t = Table(table_data, colWidths=cw)
    t.setStyle(TableStyle([
        ('GRID',          (0, 0), (-1, -1), 0.5, colors.grey),
        ('VALIGN',        (0, 0), (-1, -1), 'TOP'),
        ('TOPPADDING',    (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ('LEFTPADDING',   (0, 0), (-1, -1), 4),
    ]))
    story.append(t)
    story.append(Spacer(1, 6))

    story.append(Paragraph(_safe(phi["fax"]), small))
    story.append(Paragraph(_safe(f"Record accessed from IP: {phi['last_login_ip']}"), small))
    story.append(Spacer(1, 10))

    # Lab results table
    story.append(Paragraph("Laboratory Results", _s("lrh", bold=True, size=10)))
    story.append(Spacer(1, 4))

    lcw = [avail * 0.35, avail * 0.12, avail * 0.13, avail * 0.28, avail * 0.12]
    lab_header = [Paragraph(h, lhead) for h in
                  ["Test Name", "Result", "Units", "Ref Range", "Flag"]]
    lab_rows = [lab_header]
    for name, result, unit, flag, ref in phi["lab_results"]:
        flag_style = _s("flag", color=colors.red if flag else colors.black)
        lab_rows.append([
            Paragraph(_safe(name),   val),
            Paragraph(_safe(result), val),
            Paragraph(_safe(unit),   val),
            Paragraph(_safe(ref),    val),
            Paragraph(_safe(flag),   flag_style),
        ])
    lt = Table(lab_rows, colWidths=lcw)
    lt.setStyle(TableStyle([
        ('GRID',          (0, 0), (-1, -1), 0.5, colors.grey),
        ('BACKGROUND',    (0, 0), (-1, 0),  colors.lightgrey),
        ('VALIGN',        (0, 0), (-1, -1), 'TOP'),
        ('TOPPADDING',    (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ('LEFTPADDING',   (0, 0), (-1, -1), 4),
    ]))
    story.append(lt)
    story.append(Spacer(1, 8))

    story.append(Paragraph(_safe(f"Signed by: {phi['provider_name']}, {phi['provider_credentials']}"), val))
    story.append(Paragraph(_safe(f"Patient Address: {phi['address']}"), val))

    doc.build(story)


# ─────────────────────────────────────────────
# LAYOUT 3 — DISCHARGE SUMMARY
# ─────────────────────────────────────────────

def write_pdf_discharge(phi, path):
    """Discharge summary — multi-section with bold headers."""
    body  = _s("body")
    head  = _s("head", bold=True)
    title = _s("dtitle", bold=True, size=13, alignment=1)
    sub   = _s("dsub",   size=9,    alignment=1)

    doc = _doc(path)
    story = []

    for i, line in enumerate(render_discharge_summary(phi).split("\n")):
        if i == 0:
            story.append(Paragraph(_safe(line), title))
        elif not line.strip():
            story.append(Spacer(1, 5))
        elif line.startswith("-" * 5):
            story.append(HRFlowable(width="100%", thickness=0.5, color=colors.grey))
            story.append(Spacer(1, 2))
        elif line.isupper() and len(line.strip()) > 3:
            story.append(Paragraph(_safe(line), head))
        else:
            story.append(Paragraph(_safe(line), body))

    doc.build(story)


# ─────────────────────────────────────────────
# LAYOUT 4 — FOOTER-HEAVY (PHI in header + footer)
# ─────────────────────────────────────────────

def write_pdf_footer_heavy(phi, path):
    """Progress note — PHI rendered in every page header AND footer."""
    body = _s("fbody")
    head = _s("fhead", bold=True, size=11)

    def draw_header_footer(canvas_obj, doc):
        canvas_obj.saveState()

        # ── Header ──
        canvas_obj.setFont("Helvetica-Bold", 9)
        canvas_obj.drawCentredString(
            PAGE_W / 2, PAGE_H - 0.40 * inch,
            f"{phi['facility']} - {phi['visit_date']}"
        )
        canvas_obj.setFont("Helvetica", 8)
        canvas_obj.drawCentredString(
            PAGE_W / 2, PAGE_H - 0.58 * inch,
            f"Patient: {phi['patient_name']}  |  MRN: {phi['mrn']}  |  DOB: {phi['dob']}"
        )

        # ── Footer ──
        canvas_obj.setFont("Helvetica-Oblique", 8)
        canvas_obj.drawCentredString(
            PAGE_W / 2, 0.50 * inch,
            (f"{phi['last_name']}, {phi['first_name']}  |  DOB: {phi['dob']}  |  "
             f"MRN: {phi['mrn']}  |  SSN: {phi['ssn']}  |  Page {doc.page}")
        )
        canvas_obj.drawCentredString(
            PAGE_W / 2, 0.32 * inch,
            f"Session IP: {phi['last_login_ip']}"
        )

        canvas_obj.restoreState()

    story = []
    story.append(Paragraph("PROGRESS NOTE", head))
    story.append(Spacer(1, 6))

    skip_markers = ("-" * 10, "Page 1 of 1", "Provider:", "Session IP:")
    for line in render_footer_note(phi).split("\n")[3:]:
        if any(line.startswith(m) for m in skip_markers):
            continue
        if not line.strip():
            story.append(Spacer(1, 5))
        else:
            story.append(Paragraph(_safe(line), body))

    doc = _doc(path, top=0.9 * inch, bottom=0.8 * inch)
    doc.build(story, onFirstPage=draw_header_footer, onLaterPages=draw_header_footer)


# ─────────────────────────────────────────────
# LAYOUT 5 — REFERRAL LETTER
# ─────────────────────────────────────────────

def write_pdf_referral(phi, path):
    """Referral letter — Re: name format."""
    body = _s("rbody")
    bold = _s("rbold", bold=True)
    fac  = _s("rfac",  bold=True, size=12)

    doc = _doc(path)
    story = []

    for line in render_referral_letter(phi).split("\n"):
        if not line.strip():
            story.append(Spacer(1, 5))
        elif line.startswith("Re:"):
            story.append(Paragraph(_safe(line), bold))
        else:
            story.append(Paragraph(_safe(line), body))

    doc.build(story)


# ─────────────────────────────────────────────
# LAYOUT 6 — LAB RESULT EMAIL
# ─────────────────────────────────────────────

def write_pdf_lab_email(phi, path):
    """Lab result notification — email header format."""
    mono = _s("emono", mono=True)

    doc = _doc(path)
    story = []

    for line in render_lab_result_email(phi).split("\n"):
        if not line.strip():
            story.append(Spacer(1, 5))
        else:
            story.append(Paragraph(_safe(line), mono))

    doc.build(story)


# ─────────────────────────────────────────────
# DISPATCH TABLE
# ─────────────────────────────────────────────

PDF_WRITERS = {
    "plain_note":       write_pdf_plain,
    "table_labs":       write_pdf_table_labs,
    "discharge_summary": write_pdf_discharge,
    "footer_heavy":     write_pdf_footer_heavy,
    "referral_letter":  write_pdf_referral,
    "lab_email":        write_pdf_lab_email,
}