"""JSON investigation report. Contains hash, timestamp, models, findings, limitations; no filename or media."""
import uuid
from datetime import datetime, timezone
from io import BytesIO
from xml.sax.saxutils import escape
from app.db import database


def build_report(r: dict) -> dict:
    rep_id = "SAT-" + uuid.uuid4().hex[:12].upper()
    now = datetime.now(timezone.utc).isoformat()
    report = {"report_id": rep_id, "generated_at": now, "investigation_id": r["id"], "analysed_at": r["created_at"],
              "file": {"sha256": r["file"]["sha256"], "size_bytes": r["file"]["size_bytes"], "mime": r["file"]["mime"]},
              "assessment": r["fusion"], "modules": r["modules"], "frames": r.get("frames", []),
              "media_details": r.get("media_details"), "audio_segments": r.get("audio_segments", []),
              "processing_duration_s": r.get("processing_duration_s"),
              "limitations": sorted({l for m in r["modules"] for l in m["limitations"]}),
              "disclaimer": "AI detection is probabilistic. This report cannot establish that media is authentic or fake."}
    database.save_report(rep_id, r["id"], now, report)
    return report


def build_pdf_report(r: dict) -> tuple[str, bytes]:
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import inch
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    report = build_report(r)
    output = BytesIO()
    doc = SimpleDocTemplate(output, pagesize=letter, rightMargin=0.65 * inch, leftMargin=0.65 * inch,
                            topMargin=0.6 * inch, bottomMargin=0.6 * inch, title="SATYAM AI Media Authenticity Report")
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="SatyamTitle", parent=styles["Title"], alignment=TA_LEFT, textColor=colors.HexColor("#211a43")))
    styles.add(ParagraphStyle(name="Small", parent=styles["BodyText"], fontSize=8, leading=11))
    body = styles["BodyText"]
    story = [
        Paragraph("SATYAM AI - Media Authenticity Report", styles["SatyamTitle"]),
        Paragraph("Truth Beyond Pixels. Automated assessment, not proof of authenticity.", styles["Small"]),
        Spacer(1, 12),
        Paragraph(f"<b>Assessment:</b> {escape(r['fusion']['assessment'].replace('_', ' ').title())}", body),
        Paragraph(f"<b>Report ID:</b> {escape(report['report_id'])} &nbsp; <b>Analysis ID:</b> {escape(r['id'])}", body),
        Paragraph(f"<b>Analysed:</b> {escape(r['created_at'])} &nbsp; <b>Media:</b> {escape(r['kind'])}", body),
        Paragraph(f"<b>File type / size:</b> {escape(r['file']['mime'])} / {r['file']['size_bytes']} bytes", body),
        Paragraph(f"<b>SHA-256:</b> {escape(r['file']['sha256'])}", styles["Small"]),
        Spacer(1, 10),
    ]
    if r.get("processing_duration_s") is not None:
        story.append(Paragraph(f"<b>Processing time:</b> {r['processing_duration_s']:.3f}s", styles["Small"]))
    if r.get("media_details"):
        details = ", ".join(f"{escape(str(k).replace('_', ' '))}: {escape(str(v))}" for k, v in r["media_details"].items())
        story.append(Paragraph(f"<b>Media details:</b> {details}", styles["Small"]))
        story.append(Spacer(1, 8))

    rows = [[Paragraph("<b>Check</b>", styles["Small"]), Paragraph("<b>Status and evidence</b>", styles["Small"]),
             Paragraph("<b>Model output</b>", styles["Small"])]]
    for module in r["modules"]:
        scores = module.get("score")
        score_text = ", ".join(f"{escape(str(k))}: {float(v):.4g}" for k, v in scores.items()) if isinstance(scores, dict) and all(isinstance(v, (int, float)) for v in scores.values()) else "Not available"
        semantics = module.get("score_semantics") or "No model-score semantics supplied."
        evidence = f"{module['status']} — {module['summary']} Score semantics: {semantics}"
        rows.append([
            Paragraph(escape(module["name"]), styles["Small"]),
            Paragraph(escape(evidence), styles["Small"]),
            Paragraph(escape(score_text), styles["Small"]),
        ])
    table = Table(rows, colWidths=[1.35 * inch, 4.15 * inch, 1.25 * inch], repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eeebfa")),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#d5d1e3")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.extend([Paragraph("Evidence", styles["Heading2"]), table, Spacer(1, 10)])

    timed = [*r.get("frames", []), *r.get("audio_segments", [])]
    if timed:
        story.append(Paragraph("Sampled timeline", styles["Heading2"]))
        for item in timed:
            if "time_s" in item:
                label = f"Video frame at {item['time_s']}s"
                detail = item.get("observation") or item.get("stance", "No verdict")
            else:
                label = f"Audio {item['start_s']}–{item['end_s']}s"
                detail = f"Top model label: {item['prediction']}; raw scores: {item['scores']}"
            story.append(Paragraph(f"<b>{escape(label)}:</b> {escape(str(detail))}", styles["Small"]))

    limitations = report["limitations"]
    story.extend([Spacer(1, 10), Paragraph("Limitations", styles["Heading2"])])
    for limitation in limitations:
        story.append(Paragraph(f"- {escape(limitation)}", styles["Small"]))
    story.extend([Spacer(1, 8), Paragraph(escape(report["disclaimer"]), styles["Small"])])
    doc.build(story)
    return report["report_id"], output.getvalue()
