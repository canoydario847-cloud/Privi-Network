"""PDF rendering of sealed compliance reports (reportlab)."""

from __future__ import annotations

import io

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

INK = colors.HexColor("#13212E")
MUTED = colors.HexColor("#4A5866")
ACCENT = colors.HexColor("#2F7D6B")
RULE = colors.HexColor("#DDE2DF")
BAND = colors.HexColor("#F1F4F2")
SEV = {"critical": colors.HexColor("#B42318"), "medium": colors.HexColor("#B54708"),
       "low": colors.HexColor("#475467"), "info": colors.HexColor("#475467")}


def _esc(s) -> str:
    return (str(s) if s is not None else "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def render_pdf(body: dict, attestation: dict, report_id: str) -> bytes:
    ss = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=ss["Title"], fontName="Helvetica-Bold", fontSize=20, leading=24,
                        textColor=INK, alignment=TA_LEFT, spaceAfter=4)
    h2 = ParagraphStyle("h2", parent=ss["Heading2"], fontName="Helvetica-Bold", fontSize=12.5, leading=16,
                        textColor=INK, spaceBefore=14, spaceAfter=6)
    p = ParagraphStyle("p", parent=ss["BodyText"], fontName="Helvetica", fontSize=9.5, leading=13, textColor=INK)
    small = ParagraphStyle("small", parent=p, fontSize=8, leading=11, textColor=MUTED)
    mono = ParagraphStyle("mono", parent=p, fontName="Courier", fontSize=7.5, leading=10, textColor=INK)
    cell = ParagraphStyle("cell", parent=p, fontSize=8.5, leading=11)

    o, t, per = body["organization"], body["totals"], body["period"]
    status = body["status"].replace("_", " ").upper()
    status_color = colors.HexColor("#B54708") if body["status"] != "clean" else ACCENT

    story = [
        Paragraph("PRIVI LEDGER · AI AGENT ACTIVITY REPORT", ParagraphStyle("eyebrow", parent=small,
                  fontName="Helvetica-Bold", textColor=ACCENT, spaceAfter=6)),
        Paragraph(_esc(o["name"]), h1),
        Paragraph(f"Organization {_esc(o['org_id'])} · Period {_esc(per['since'] or 'start')} to "
                  f"{_esc(per['until'] or 'now')} · Generated {_esc(body['generated_at'])} · Report {_esc(report_id)}", small),
        Spacer(1, 10),
        Paragraph(f'<font color="{status_color.hexval()}"><b>STATUS: {status}</b></font>', p),
        Paragraph("Summary", h2),
    ]

    def table(data, widths, header=True):
        tb = Table(data, colWidths=widths, repeatRows=1 if header else 0)
        style = [("FONT", (0, 0), (-1, -1), "Helvetica", 8.5), ("TEXTCOLOR", (0, 0), (-1, -1), INK),
                 ("LINEBELOW", (0, 0), (-1, -1), 0.5, RULE), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                 ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]
        if header:
            style += [("BACKGROUND", (0, 0), (-1, 0), BAND), ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 8.5)]
        tb.setStyle(TableStyle(style))
        return tb

    story.append(table(
        [["Agent logs", "Actions", "Failures", "Blocked", "Human approvals", "Sensitive actions"],
         [t["streams"], t["entries"], t["failures"], t["blocked"], t["approvals"], t["sensitive_actions"]]],
        [1.05 * inch] * 6))
    if t.get("action_counts"):
        story += [Spacer(1, 6), Paragraph("Actions by type: " + ", ".join(
            f"{_esc(k)} {v}" for k, v in sorted(t["action_counts"].items())), small)]

    story.append(Paragraph("Findings", h2))
    if body["findings"]:
        rows = [["Severity", "Log", "Finding"]]
        for f in body["findings"]:
            rows.append([Paragraph(f'<font color="{SEV.get(f["severity"], MUTED).hexval()}"><b>{f["severity"].upper()}</b></font>', cell),
                         Paragraph(_esc(f["stream_id"] or "—"), cell), Paragraph(_esc(f["finding"]), cell)])
        story.append(table(rows, [0.85 * inch, 1.6 * inch, 3.85 * inch]))
    else:
        story.append(Paragraph("No findings.", p))

    story.append(Paragraph("Agent logs", h2))
    rows = [["Log", "Actions", "Intact", "On chain", "Actors"]]
    for s in body["streams"]:
        cp = s["onchain_checkpoint"]
        rows.append([Paragraph(_esc(s["stream_id"]), cell), s["entries_in_period"],
                     "yes" if s["integrity"]["intact"] else "NO",
                     f"block {cp.get('block_number')}" if cp.get("anchored") else "not yet",
                     Paragraph(_esc(", ".join(s["actors"])), cell)])
    story.append(table(rows, [1.7 * inch, 0.65 * inch, 0.6 * inch, 0.95 * inch, 2.4 * inch]))

    fails = [(s["stream_id"], f) for s in body["streams"] for f in s["failures"]]
    if fails:
        story.append(Paragraph("Failed actions", h2))
        rows = [["Log", "Entry", "Summary"]] + [[Paragraph(_esc(sid), cell), f["seq"], Paragraph(_esc(f["summary"]), cell)]
                                               for sid, f in fails]
        story.append(table(rows, [1.7 * inch, 0.6 * inch, 4.0 * inch]))

    story.append(Paragraph("Verification", h2))
    story.append(Paragraph("Report hash (SHA-256 over the canonical JSON report body):", p))
    story.append(Paragraph(_esc(attestation["report_hash"]), mono))
    story.append(Spacer(1, 6))
    if attestation.get("anchored"):
        chain = f" (chain {attestation['chain_id']})" if attestation.get("chain_id") else ""
        story.append(Paragraph(f"Sealed on chain (the Privi Devnet, until the Privi mainnet){_esc(chain)} in block "
                               f"{_esc(attestation.get('block_number'))}, transaction:", p))
        story.append(Paragraph(_esc(attestation["tx_hash"]), mono))
        story.append(Spacer(1, 6))
        story.append(Paragraph("To verify, pass the JSON report to Privi Ledger <b>ledger_verify_report</b>, or check the "
                               "hash, transaction and Merkle proof with Privi Anchor <b>anchor_verify</b>. Any change "
                               "to the report changes its hash and fails verification.", p))
    else:
        story.append(Paragraph(f"Not sealed on chain: {_esc(attestation.get('reason', 'anchoring not configured'))}.", p))
    story += [Spacer(1, 10), Paragraph(_esc(body["method"]), small)]

    buf = io.BytesIO()

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(MUTED)
        canvas.drawString(0.75 * inch, 0.5 * inch, f"Privi Ledger · {o['name']} · {report_id}")
        canvas.drawRightString(LETTER[0] - 0.75 * inch, 0.5 * inch, f"Page {doc.page}")
        canvas.restoreState()

    SimpleDocTemplate(buf, pagesize=LETTER, leftMargin=0.75 * inch, rightMargin=0.75 * inch,
                      topMargin=0.75 * inch, bottomMargin=0.8 * inch,
                      title=f"AI Agent Activity Report: {o['name']}", author="Privi Ledger").build(
        story, onFirstPage=footer, onLaterPages=footer)
    return buf.getvalue()
