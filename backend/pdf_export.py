"""Render a finished biography into a printable PDF book."""
import concurrent.futures as futures
import io
from datetime import date

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY
from reportlab.lib.pagesizes import A5
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (BaseDocTemplate, Frame, Image, NextPageTemplate,
                                PageBreak, PageTemplate, Paragraph, Spacer)

from . import images as image_svc

INK = colors.HexColor("#1d1a17")
MUTED = colors.HexColor("#7a6f64")
ACCENT = colors.HexColor("#8a5a2b")


def _styles():
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("t", parent=base["Title"], fontName="Times-Bold",
                                fontSize=30, leading=34, textColor=INK, spaceAfter=10),
        "subtitle": ParagraphStyle("st", parent=base["Normal"], fontName="Times-Italic",
                                   fontSize=13, leading=18, alignment=TA_CENTER,
                                   textColor=MUTED),
        "dedication": ParagraphStyle("d", parent=base["Normal"], fontName="Times-Italic",
                                     fontSize=12, leading=20, alignment=TA_CENTER,
                                     textColor=INK),
        "chnum": ParagraphStyle("cn", parent=base["Normal"], fontName="Helvetica-Bold",
                                fontSize=9, leading=12, alignment=TA_CENTER,
                                textColor=ACCENT, spaceAfter=6),
        "chtitle": ParagraphStyle("ct", parent=base["Normal"], fontName="Times-Bold",
                                  fontSize=21, leading=25, alignment=TA_CENTER,
                                  textColor=INK, spaceAfter=4),
        "era": ParagraphStyle("e", parent=base["Normal"], fontName="Times-Italic",
                              fontSize=10, alignment=TA_CENTER, textColor=MUTED,
                              spaceAfter=14),
        "body": ParagraphStyle("b", parent=base["Normal"], fontName="Times-Roman",
                               fontSize=10.8, leading=16.4, alignment=TA_JUSTIFY,
                               firstLineIndent=12, spaceAfter=2, textColor=INK),
        "caption": ParagraphStyle("cap", parent=base["Normal"], fontName="Times-Italic",
                                  fontSize=8.6, leading=11, alignment=TA_CENTER,
                                  textColor=MUTED, spaceBefore=4, spaceAfter=12),
        "toc": ParagraphStyle("toc", parent=base["Normal"], fontName="Times-Roman",
                              fontSize=11, leading=19, textColor=INK),
        "h": ParagraphStyle("h", parent=base["Normal"], fontName="Times-Bold",
                            fontSize=16, leading=20, alignment=TA_CENTER,
                            textColor=INK, spaceAfter=16),
    }


def _esc(text: str) -> str:
    return (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def _prefetch(urls: list) -> dict:
    out = {}
    if not urls:
        return out
    with futures.ThreadPoolExecutor(max_workers=6) as pool:
        for url, data in zip(urls, pool.map(image_svc.fetch_bytes, urls)):
            if data:
                out[url] = data
    return out


def build_pdf(bio: dict, author_email: str = "") -> bytes:
    payload = bio["payload"]
    st = _styles()
    buf = io.BytesIO()

    doc = BaseDocTemplate(buf, pagesize=A5,
                          leftMargin=17 * mm, rightMargin=17 * mm,
                          topMargin=18 * mm, bottomMargin=18 * mm,
                          title=payload.get("title", "Biography"),
                          author=author_email or "Lifescroll")
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="f")

    def plain(canvas, _doc):
        canvas.saveState()
        canvas.setFont("Times-Roman", 8)
        canvas.setFillColor(MUTED)
        canvas.drawCentredString(A5[0] / 2, 11 * mm, str(_doc.page))
        canvas.restoreState()

    def bare(canvas, _doc):
        pass

    doc.addPageTemplates([PageTemplate(id="bare", frames=[frame], onPage=bare),
                          PageTemplate(id="book", frames=[frame], onPage=plain)])

    story = [NextPageTemplate("bare"), Spacer(1, 42 * mm),
             Paragraph(_esc(payload.get("title", "A Life")), st["title"]),
             Spacer(1, 4 * mm),
             Paragraph(_esc(payload.get("subtitle", "")), st["subtitle"]),
             Spacer(1, 30 * mm),
             Paragraph("Written with Lifescroll", st["subtitle"])]
    if author_email:
        story.append(Paragraph(_esc(author_email), st["subtitle"]))
    story.append(Paragraph(date.today().strftime("%B %Y"), st["subtitle"]))
    story.append(PageBreak())

    if payload.get("dedication"):
        story += [Spacer(1, 60 * mm),
                  Paragraph(_esc(payload["dedication"]), st["dedication"]), PageBreak()]

    story += [NextPageTemplate("book"), Paragraph("Contents", st["h"])]
    for ch in payload.get("chapters", []):
        story.append(Paragraph(
            f"{ch['number']}.&nbsp;&nbsp;{_esc(ch['title'])}"
            + (f" <font color='#7a6f64'><i>— {_esc(ch.get('era',''))}</i></font>"
               if ch.get("era") else ""), st["toc"]))
    story.append(PageBreak())

    all_urls = [img["url"] for ch in payload.get("chapters", [])
                for img in ch.get("images", [])]
    cache = _prefetch(all_urls)

    for ch in payload.get("chapters", []):
        story += [Spacer(1, 12 * mm),
                  Paragraph(f"CHAPTER {ch['number']}", st["chnum"]),
                  Paragraph(_esc(ch["title"]), st["chtitle"])]
        if ch.get("era"):
            story.append(Paragraph(_esc(ch["era"]), st["era"]))
        story.append(Spacer(1, 4 * mm))

        paragraphs = [p for p in (ch.get("text") or "").split("\n") if p.strip()]
        pics = list(ch.get("images", []))
        # Spread illustrations evenly through the chapter.
        slots = {}
        if pics and paragraphs:
            gap = max(1, len(paragraphs) // (len(pics) + 1))
            for i, pic in enumerate(pics):
                slots.setdefault(min(len(paragraphs) - 1, (i + 1) * gap), []).append(pic)

        for idx, para in enumerate(paragraphs):
            story.append(Paragraph(_esc(para.strip()), st["body"]))
            for pic in slots.get(idx, []):
                data = cache.get(pic["url"])
                if not data:
                    continue
                try:
                    img = Image(io.BytesIO(data))
                    ratio = img.imageHeight / float(img.imageWidth)
                    img.drawWidth = doc.width
                    img.drawHeight = doc.width * ratio
                    story += [Spacer(1, 5 * mm), img]
                    if pic.get("caption"):
                        story.append(Paragraph(_esc(pic["caption"]), st["caption"]))
                    else:
                        story.append(Spacer(1, 5 * mm))
                except Exception:
                    continue
        story.append(PageBreak())

    story += [Paragraph("Afterword", st["h"]),
              Paragraph(_esc(
                  f"This book was generated by Lifescroll from a spoken life-story "
                  f"interview. It contains {payload.get('word_count', 0):,} words across "
                  f"{len(payload.get('chapters', []))} chapters, illustrated with "
                  f"{len(all_urls)} generated images. Every fact came from the person "
                  f"who told it."), st["body"])]

    doc.build(story)
    return buf.getvalue()
