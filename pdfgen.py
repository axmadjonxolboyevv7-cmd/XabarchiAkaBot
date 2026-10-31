import os, time
from xml.sax.saxutils import escape
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

FONT = "Helvetica"
for p in ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/dejavu/DejaVuSans.ttf", "DejaVuSans.ttf"):
    if os.path.exists(p):
        pdfmetrics.registerFont(TTFont("DJ", p)); FONT = "DJ"; break

def make_pdf(path, title, rows):
    st = ParagraphStyle("n", fontName=FONT, fontSize=10, leading=14)
    h = ParagraphStyle("h", fontName=FONT, fontSize=16, leading=20)
    icons = {"deleted": "[O'CHIRILGAN]", "edited": "[TAHRIRLANGAN]", "ok": ""}
    doc = SimpleDocTemplate(path, pagesize=A4, title=title)
    out = [Paragraph(escape(title), h), Spacer(1, 12)]
    for r in rows:
        t = time.strftime("%d.%m.%Y %H:%M", time.localtime(r["date"]))
        media = f" [{r['type']}]" if r["type"] != "text" else ""
        line = f"<b>{escape(r['from_name'] or '?')}</b> — {t} {icons.get(r['status'], '')}{media}<br/>{escape(r['text'] or '')}"
        out += [Paragraph(line, st), Spacer(1, 6)]
    doc.build(out)
