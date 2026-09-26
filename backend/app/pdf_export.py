import io
from datetime import datetime

from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

HUE_HEX = {
    "blue": "#3E6690",
    "sage": "#587555",
    "clay": "#A15E37",
    "mauve": "#83557A",
    "ochre": "#93732A",
    "slate": "#545F6E",
}

MARGIN = 48


def _wrap(c: canvas.Canvas, text: str, font: str, size: float, max_width: float):
    c.setFont(font, size)
    words = text.split()
    lines, current = [], ""
    for word in words:
        candidate = (current + " " + word).strip()
        if c.stringWidth(candidate, font, size) <= max_width:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines or [""]


def build_pdf(boards: list) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    page_w, page_h = A4
    content_w = page_w - MARGIN * 2
    y = [page_h - MARGIN]

    def ensure_space(h):
        if y[0] - h < MARGIN:
            c.showPage()
            y[0] = page_h - MARGIN

    def set_y(delta):
        y[0] -= delta

    c.setFillColor(HexColor("#1C232D"))
    c.setFont("Helvetica-Bold", 20)
    c.drawString(MARGIN, y[0], "Scatterboard: Project Summary")
    set_y(20)

    c.setFillColor(HexColor("#626E7C"))
    c.setFont("Helvetica", 10)
    date_str = datetime.now().strftime("%B %d, %Y")
    count_label = f"{len(boards)} board" + ("" if len(boards) == 1 else "s")
    c.drawString(MARGIN, y[0], f"Generated {date_str}  ·  {count_label}")
    set_y(28)

    if not boards:
        c.setFillColor(HexColor("#8C949E"))
        c.setFont("Helvetica", 11)
        c.drawString(MARGIN, y[0], "No boards yet.")

    for board in boards:
        hue = HUE_HEX.get(board.get("color", "blue"), HUE_HEX["blue"])
        tasks = board.get("tasks", [])
        total = len(tasks)
        done = sum(1 for t in tasks if t.get("done"))

        ensure_space(30)
        c.setFillColor(HexColor(hue))
        c.rect(MARGIN, y[0] - 12, 4, 16, fill=1, stroke=0)
        c.setFillColor(HexColor("#1C232D"))
        c.setFont("Helvetica-Bold", 13)
        c.drawString(MARGIN + 12, y[0], board.get("title") or "Untitled board")
        set_y(22)

        description = board.get("description")
        if description:
            c.setFont("Helvetica", 9.5)
            c.setFillColor(HexColor("#626E7C"))
            for line in _wrap(c, description, "Helvetica", 9.5, content_w - 12):
                ensure_space(13)
                c.drawString(MARGIN + 12, y[0], line)
                set_y(13)
            set_y(2)

        ensure_space(14)
        bar_w, bar_h = 140, 5
        c.setFillColor(HexColor("#E6E9ED"))
        c.roundRect(MARGIN + 12, y[0] - bar_h, bar_w, bar_h, 2, fill=1, stroke=0)
        if total:
            c.setFillColor(HexColor(hue))
            fill_w = max(2, bar_w * (done / total))
            c.roundRect(MARGIN + 12, y[0] - bar_h, fill_w, bar_h, 2, fill=1, stroke=0)
        c.setFont("Helvetica", 8.5)
        c.setFillColor(HexColor("#8C949E"))
        label = f"{done} of {total} done" if total else "No tasks"
        c.drawString(MARGIN + 12 + bar_w + 8, y[0] - bar_h + 4, label)
        set_y(bar_h + 14)

        c.setFont("Helvetica", 10.5)
        for task in tasks:
            lines = _wrap(c, task.get("text", ""), "Helvetica", 10.5, content_w - 30)
            block_h = len(lines) * 13 + 6
            ensure_space(block_h)

            box_y = y[0] - 8
            if task.get("done"):
                c.setFillColor(HexColor(hue))
                c.roundRect(MARGIN + 12, box_y, 9, 9, 2, fill=1, stroke=0)
            else:
                c.setStrokeColor(HexColor("#96A2A8"))
                c.roundRect(MARGIN + 12, box_y, 9, 9, 2, fill=0, stroke=1)

            c.setFont("Helvetica", 10.5)
            c.setFillColor(HexColor("#A5AAB2") if task.get("done") else HexColor("#1E2630"))
            for i, line in enumerate(lines):
                c.drawString(MARGIN + 28, y[0] - i * 13, line)
            if task.get("done") and lines:
                width = c.stringWidth(lines[0], "Helvetica", 10.5)
                c.setStrokeColor(HexColor("#A5AAB2"))
                c.line(MARGIN + 28, y[0] + 3, MARGIN + 28 + width, y[0] + 3)

            set_y(block_h)

        set_y(16)

    c.save()
    return buf.getvalue()
