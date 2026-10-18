from __future__ import annotations

import io
import math
import re
import secrets
import time
import cv2
import numpy as np
from flask import Flask, abort, jsonify, render_template, request, send_file
from fontTools.feaLib.builder import addOpenTypeFeaturesFromString
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.pens.t2CharStringPen import T2CharStringPen
from fontTools.ttLib import TTFont

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 60 * 1024 * 1024
PAGE_W, PAGE_H, SCALE = 595, 842, 3
MARKER_INSET, MARKER_SIZE = 10, 7
MARGIN, ROW_TOP, ROW_H, GROUP_GAP = 28, 82, 29, 12
CELL_X, CELL_W, CELL_H = 19, 73, 21
VARIANT_GAP = 3
UPPER_CHARS = list("ABCDEFGHIJKLMNOPQRSTUVWXYZÄÖÜ")
LOWER_CHARS = list("abcdefghijklmnopqrstuvwxyzäöüß")
DIGIT_CHARS = list("0123456789")
EXTRA_CHARS = list("!?.,:;+-*/=()[]{}_\\'\"@#%&<>|^~`$")
PAGE_GROUPS = [UPPER_CHARS + DIGIT_CHARS[:5], LOWER_CHARS + DIGIT_CHARS[5:9], DIGIT_CHARS[9:] + EXTRA_CHARS]
PAGE_COUNT = len(PAGE_GROUPS)
CHARS = [character for group in PAGE_GROUPS for character in group]
if len(set(CHARS)) != len(CHARS):
    raise ValueError("Vorlagenzeichen müssen eindeutig sein.")
CHAR_PAGE_INDEX = {character: page for page, characters in enumerate(PAGE_GROUPS) for character in characters}

SAMPLES = {}
SAMPLE_TTL = 60 * 60
SAMPLE_LIMIT = 32


def prune_samples(now: float | None = None) -> None:
    now = time.monotonic() if now is None else now
    for token, session in list(SAMPLES.items()):
        if now - session["created"] > SAMPLE_TTL:
            SAMPLES.pop(token, None)


def get_sample(token: str | None) -> dict | None:
    prune_samples()
    return SAMPLES.get(token)


def page_glyphs(page_no: int) -> list[str]:
    if page_no < 0 or page_no >= PAGE_COUNT:
        raise IndexError("Ungültige Vorlagenseite.")
    return PAGE_GROUPS[page_no]


def layout(index: int, page_index: int | None = None) -> tuple[int, int, int]:
    """Return a character's template cell. Specify page_index for page-local indices."""
    if page_index is None:
        if index < 0 or index >= len(CHARS):
            raise IndexError("Ungültiger Vorlagenindex.")
        page_index = CHAR_PAGE_INDEX[CHARS[index]]
        local = PAGE_GROUPS[page_index].index(CHARS[index])
    else:
        if page_index < 0 or page_index >= PAGE_COUNT or index < 0 or index >= len(PAGE_GROUPS[page_index]):
            raise IndexError("Ungültige Vorlagenseite oder -zelle.")
        local = index
    row, col = local // 2, local % 2
    return page_index, row, col


def cell_box(index: int, variant: int, page_index: int | None = None) -> tuple[float, float, float, float]:
    if variant < 0 or variant > 2:
        raise IndexError("Ungültige Variantenposition.")
    _, row, col = layout(index, page_index)
    group_w = (PAGE_W - 2 * MARGIN - GROUP_GAP) / 2
    if page_index is None:
        page_index = layout(index)[0]
    gx = MARGIN + col * (group_w + GROUP_GAP)
    x = gx + CELL_X + variant * (CELL_W + VARIANT_GAP)
    y = ROW_TOP + row * ROW_H + (ROW_H - CELL_H) / 2
    return x, y, CELL_W, CELL_H


def pdf_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def make_template_pdf() -> bytes:
    pages = []
    for page_no in range(PAGE_COUNT):
        ops = [
            "0.16 0.22 0.19 rg",
            "0.05 0.07 0.05 rg",
            *[f"{x} {y} {MARKER_SIZE} {MARKER_SIZE} re f" for x, y in ((MARKER_INSET, MARKER_INSET), (PAGE_W-MARKER_INSET-MARKER_SIZE, MARKER_INSET), (PAGE_W-MARKER_INSET-MARKER_SIZE, PAGE_H-MARKER_INSET-MARKER_SIZE), (MARKER_INSET, PAGE_H-MARKER_INSET-MARKER_SIZE))],
            "BT /F1 22 Tf 30 799 Td (Federwerk) Tj ET",
            "BT /F1 9 Tf 30 779 Td (DEINE HANDSCHRIFT. DEIN FONT.) Tj ET",
            "0.30 0.37 0.32 rg",
            "BT /F1 9 Tf 30 762 Td (Schreibe jedes Zeichen in die Felder. Bis zu drei Varianten pro Zeichen.) Tj ET",
            "BT /F1 8 Tf 30 748 Td (Dunkler Stift, gerade Aufnahme, ganzes Blatt sichtbar. Varianten 1-3; leere Felder sind erlaubt.) Tj ET",
            "0.78 0.82 0.78 RG 0.6 w 28 737 m 567 737 l S",
        ]
        page_chars = PAGE_GROUPS[page_no]
        group_w = (PAGE_W - 2 * MARGIN - GROUP_GAP) / 2
        for local, char in enumerate(page_chars):
            _, row, col = layout(local, page_no)
            gx = MARGIN + col * (group_w + GROUP_GAP)
            top = ROW_TOP + row * ROW_H
            baseline = PAGE_H - top - ROW_H / 2 - 2.5
            ops += ["0.18 0.23 0.20 rg", f"BT /F1 10 Tf {gx:.2f} {baseline:.2f} Td ({pdf_escape(char)}) Tj ET"]
            for variant in range(3):
                x, yt, w, h = cell_box(local, variant, page_no)
                y = PAGE_H - yt - h
                ops += ["0.79 0.83 0.78 RG 0.55 w", f"{x:.2f} {y:.2f} {w:.2f} {h:.2f} re S"]
        ops += ["0.45 0.50 0.46 rg", f"BT /F1 8 Tf 28 20 Td (Federwerk  |  Vorlage {page_no + 1} / {PAGE_COUNT}  |  Seite {len(page_chars)} Zeichen  |  Orientierungspunkte nicht abschneiden) Tj ET"]
        pages.append("\n".join(ops).encode("latin-1"))

    objects: list[bytes] = []
    page_ids, content_ids = [], []
    next_id = 5
    for _ in pages:
        page_ids.append(next_id)
        content_ids.append(next_id + 1)
        next_id += 2
    objects.extend([b"<< /Type /Catalog /Pages 2 0 R >>", b"", b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"])
    kids = " ".join(f"{pid} 0 R" for pid in page_ids)
    objects[1] = f"<< /Type /Pages /Kids [{kids}] /Count {len(pages)} >>".encode()
    for pid, cid, content in zip(page_ids, content_ids, pages):
        objects.extend([f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {PAGE_W} {PAGE_H}] /Resources << /Font << /F1 3 0 R >> >> /Contents {cid} 0 R >>".encode(), f"<< /Length {len(content)} >>\nstream\n".encode() + content + b"\nendstream"])
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for number, obj in enumerate(objects, 1):
        offsets.append(out.tell())
        out.write(f"{number} 0 obj\n".encode() + obj + b"\nendobj\n")
    xref = out.tell()
    out.write(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
    for offset in offsets[1:]:
        out.write(f"{offset:010d} 00000 n \n".encode())
    out.write(f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode())
    return out.getvalue()


def order_corners(points: np.ndarray) -> np.ndarray:
    result = np.zeros((4, 2), dtype="float32")
    sums, diffs = points.sum(axis=1), np.diff(points, axis=1).reshape(-1)
    result[0], result[2] = points[np.argmin(sums)], points[np.argmax(sums)]
    result[1], result[3] = points[np.argmin(diffs)], points[np.argmax(diffs)]
    return result


def find_registration_markers(gray: np.ndarray) -> np.ndarray | None:
    """Find the four small solid square fiducials in the margin of a Federwerk page."""
    height, width = gray.shape[:2]
    contours, _ = cv2.findContours(cv2.threshold(gray, 130, 255, cv2.THRESH_BINARY_INV)[1], cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    corners: dict[str, list[tuple[float, np.ndarray]]] = {"tl": [], "tr": [], "br": [], "bl": []}
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        if min(w, h) < 5 or max(w, h) > min(width, height) * 0.045:
            continue
        if abs(w-h) > max(3, max(w, h)*0.35) or cv2.contourArea(contour) < w*h*0.42:
            continue
        cx, cy = x+w/2, y+h/2
        if cx < width*0.40 and cy < height*0.25:
            key, score = "tl", (cx/width)**2 + (cy/height)**2
        elif cx > width*0.60 and cy < height*0.25:
            key, score = "tr", ((width-cx)/width)**2 + (cy/height)**2
        elif cx > width*0.60 and cy > height*0.75:
            key, score = "br", ((width-cx)/width)**2 + ((height-cy)/height)**2
        elif cx < width*0.40 and cy > height*0.75:
            key, score = "bl", (cx/width)**2 + ((height-cy)/height)**2
        else:
            continue
        corners[key].append((score, np.array([cx, cy], dtype="float32")))
    if any(not candidates for candidates in corners.values()):
        return None
    return np.array([min(corners[key], key=lambda item: item[0])[1] for key in ("tl", "tr", "br", "bl")], dtype="float32")


def straighten(image: np.ndarray) -> np.ndarray:
    height, width = image.shape[:2]
    scale = min(1.0, 1800 / width, 2500 / height)
    small = cv2.resize(image, (round(width * scale), round(height * scale))) if scale < 1.0 else image
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY) if small.ndim == 3 else small
    out_w, out_h = PAGE_W * SCALE, PAGE_H * SCALE
    fiducials = find_registration_markers(gray)
    if fiducials is not None:
        inset = (MARKER_INSET + MARKER_SIZE/2) * SCALE
        target = np.array([[inset, inset], [(PAGE_W*1.0-(MARKER_INSET+MARKER_SIZE/2))*SCALE, inset], [(PAGE_W*1.0-(MARKER_INSET+MARKER_SIZE/2))*SCALE, (PAGE_H*1.0-(MARKER_INSET+MARKER_SIZE/2))*SCALE], [inset, (PAGE_H*1.0-(MARKER_INSET+MARKER_SIZE/2))*SCALE]], dtype="float32")
        matrix = cv2.getPerspectiveTransform(fiducials, target)
        return cv2.warpPerspective(small, matrix, (out_w, out_h), borderValue=(255, 255, 255))
    found = cv2.findContours(cv2.threshold(gray, 180, 255, cv2.THRESH_BINARY_INV)[1], cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    candidates = sorted(found[-2], key=cv2.contourArea, reverse=True)
    corners = None
    for contour in candidates[:30]:
        perimeter = cv2.arcLength(contour, True)
        approx = cv2.approxPolyDP(contour, 0.018 * perimeter, True)
        if len(approx) == 4 and cv2.contourArea(approx) > gray.size * 0.14:
            pts = order_corners(approx.reshape(4, 2).astype("float32"))
            width_ratio = (np.linalg.norm(pts[1] - pts[0])) / max(1, np.linalg.norm(pts[3] - pts[0]))
            if 0.52 <= width_ratio <= 0.9:
                corners = pts
                break
    if corners is not None:
        target = np.array([[MARGIN*SCALE, MARGIN*SCALE], [(PAGE_W-MARGIN)*SCALE, MARGIN*SCALE], [(PAGE_W-MARGIN)*SCALE, (PAGE_H-MARGIN)*SCALE], [MARGIN*SCALE, (PAGE_H-MARGIN)*SCALE]], dtype="float32")
        matrix = cv2.getPerspectiveTransform(corners, target)
        return cv2.warpPerspective(small, matrix, (out_w, out_h), borderValue=(255, 255, 255))
    # A flatbed scan may crop the registration frame; its page proportions still provide a reliable fallback.
    return cv2.resize(small, (out_w, out_h), interpolation=cv2.INTER_CUBIC)


def glyph_profile(character: str | None) -> tuple[int, int]:
    if character is None:
        return 690, 0
    if character in "ÄÖÜ":
        return 820, 0
    if character in "äöü":
        return 610, 0
    if character in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
        return 700, 0
    if character in "bdfhklt":
        return 700, 0
    if character in "gjpqy":
        return 650, 150
    if character in "abcdefghijklmnopqrstuvwxyz":
        return 500, 0
    if character in "0123456789":
        return 580, 0
    if character in ".,:;`'’":
        return 365, 35
    if character in "!?()[]{}|":
        return 650, 0
    return 540, 0


def trace_ink(binary: np.ndarray, character: str | None = None) -> dict | None:
    ink = cv2.countNonZero(binary) / max(1, binary.size)
    if ink < 0.0025 or ink > 0.44:
        return None
    contours, _ = cv2.findContours(binary, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
    kept = [contour for contour in contours if cv2.contourArea(contour) >= 1.3 or len(contour) >= 7]
    if not kept:
        return None
    points = np.vstack([contour.reshape(-1, 2) for contour in kept])
    x0, y0 = points.min(axis=0).astype(float)
    x1, y1 = points.max(axis=0).astype(float)
    if x1 - x0 < 2 or y1 - y0 < 2:
        return None
    target_height, descent = glyph_profile(character)
    unit_scale = min(760 / (x1-x0), target_height / (y1-y0))
    paths = []
    for contour in kept:
        vertices = cv2.approxPolyDP(contour, 0.55, True).reshape(-1, 2)
        if len(vertices) < 3:
            continue
        paths.append([[round(55 + (float(px)-x0)*unit_scale, 1), round((y1-float(py))*unit_scale-descent, 1)] for px, py in vertices])
    if not paths:
        return None
    width_units = max(260, round((x1-x0)*unit_scale + 115))
    quality = max(0.05, min(0.99, 0.55 + min(ink, 0.16)*2.0 - max(0, ink-0.25)*1.1))
    return {"contours": paths, "advance": width_units, "confidence": round(quality, 2), "ink": round(float(ink), 3)}


def trace_cell(page: np.ndarray, box: tuple[float, float, float, float], character: str | None = None) -> dict | None:
    x, top, width, height = box
    margin = 3.3
    crop = page[round((top + margin)*SCALE):round((top + height - margin)*SCALE), round((x + margin)*SCALE):round((x + width - margin)*SCALE)]
    if crop.size == 0:
        return None
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if crop.ndim == 3 else crop
    return trace_ink(cv2.threshold(gray, 188, 255, cv2.THRESH_BINARY_INV)[1], character)


def parse_glyph_name(character: str) -> str:
    # Unicode names avoid AGL differences between fontTools releases and safely handle punctuation.
    return "uni%04X" % ord(character)


def paths_to_commands(paths: list[list[list[float]]], ttf_pen=None, cff_pen=None) -> None:
    pen = ttf_pen or cff_pen
    for contour in paths:
        if len(contour) < 3:
            continue
        pen.moveTo(tuple(contour[0]))
        for point in contour[1:]:
            pen.lineTo(tuple(point))
        pen.closePath()


def build_font(glyphs: list[dict], flavor: str) -> bytes:
    if any(not isinstance(g, dict) for g in glyphs):
        raise ValueError("Die Font-Zeichendaten sind ungültig.")
    valid = {g["char"]: g for g in glyphs if isinstance(g.get("char"), str) and len(g["char"]) == 1 and g["char"] in CHARS}
    missing = [char for char in CHARS if char not in valid]
    if missing:
        preview = " ".join(repr(c) for c in missing[:18])
        raise ValueError(f"Fehlende Zeichen: {preview}" + (" …" if len(missing) > 18 else ""))
    if len(valid) != len([g for g in glyphs if g.get("char") in CHARS]):
        raise ValueError("Jedes Vorlagenzeichen darf nur einmal zugeordnet sein.")
    variants: dict[str, list[dict]] = {}
    names: list[str] = [".notdef", "space"]
    cmap = {32: "space"}
    base_for_char = {}
    for char in CHARS:
        g = valid[char]
        try:
            advance = int(g.get("advance", 610))
        except (TypeError, ValueError, OverflowError):
            advance = 610
        base_name = parse_glyph_name(char)
        base_for_char[char] = base_name
        cmap[ord(char)] = base_name
        names.append(base_name)
        shapes = g.get("variants", [])
        if not isinstance(shapes, list) or len(shapes) > 3:
            raise ValueError(f"Für {char!r} sind höchstens drei Handschriftproben erlaubt.")
        usable = [v for v in shapes if isinstance(v, dict) and isinstance(v.get("contours"), list)]
        for sample in usable:
            if len(sample["contours"]) > 80 or any(not isinstance(contour, list) or len(contour) > 1000 for contour in sample["contours"]):
                raise ValueError(f"Die Vektordaten für {char!r} sind zu umfangreich.")
            for contour in sample["contours"]:
                if len(contour) < 3 or any(not isinstance(point, (list, tuple)) or len(point) != 2 or any(not isinstance(value, (int, float)) or not math.isfinite(value) or abs(value) > 10000 for value in point) for point in contour):
                    raise ValueError(f"Ungültige Vektordaten für {char!r}.")
        if not usable:
            raise ValueError(f"Für {char!r} fehlt eine lesbare Handschriftprobe.")
        variants[char] = usable[:3]
        for index in range(1, len(variants[char])):
            names.append(f"{base_name}.alt{index:02d}")

    # de-duplicate codepoint aliases without changing glyph order.
    names = list(dict.fromkeys(names))
    metrics = {}
    for char in CHARS:
        g = valid[char]
        try:
            advance = int(g.get("advance", 610))
        except (TypeError, ValueError, OverflowError):
            advance = 610
        metrics[base_for_char[char]] = (max(250, min(1200, advance)), 55)
        for index in range(1, len(variants[char])):
            try:
                alternate_advance = int(variants[char][index].get("advance", advance))
            except (TypeError, ValueError, OverflowError):
                alternate_advance = advance
            metrics[f"{base_for_char[char]}.alt{index:02d}"] = (max(250, min(1200, alternate_advance)), 55)
    metrics.update({".notdef": (620, 50), "space": (300, 0)})
    is_ttf = flavor == "ttf"
    fb = FontBuilder(1000, isTTF=is_ttf)
    fb.setupGlyphOrder(names)
    fb.setupCharacterMap(cmap)
    fb.setupHorizontalMetrics(metrics)
    fb.setupHorizontalHeader(ascent=920, descent=-220)
    fb.setupNameTable({"familyName": "Federwerk Handschrift", "styleName": "Regular", "uniqueFontIdentifier": "Federwerk-Handschrift-1.0", "fullName": "Federwerk Handschrift", "psName": "FederwerkHandschrift", "version": "Version 1.0"})
    fb.setupOS2(sTypoAscender=920, sTypoDescender=-220, usWinAscent=960, usWinDescent=250, sxHeight=500, sCapHeight=710)
    fb.setupPost()
    if is_ttf:
        glyphs_out = {}
        for glyph_name in names:
            pen = TTGlyphPen(None)
            if glyph_name == ".notdef":
                pen.moveTo((50, 0)); pen.lineTo((570, 0)); pen.lineTo((570, 700)); pen.lineTo((50, 700)); pen.closePath()
            else:
                for char in CHARS:
                    base = base_for_char[char]
                    if glyph_name == base:
                        paths_to_commands(variants[char][0]["contours"], ttf_pen=pen)
                    elif glyph_name.startswith(base + ".alt"):
                        match = re.search(r"\.alt(\d+)$", glyph_name)
                        index = int(match.group(1)) if match else 0
                        if index < len(variants[char]): paths_to_commands(variants[char][index]["contours"], ttf_pen=pen)
            glyphs_out[glyph_name] = pen.glyph()
        fb.setupGlyf(glyphs_out)
        fb.setupMaxp()
    else:
        char_strings = {}
        for glyph_name in names:
            width = metrics[glyph_name][0]
            pen = T2CharStringPen(width, None)
            if glyph_name == ".notdef":
                pen.moveTo((50, 0)); pen.lineTo((570, 0)); pen.lineTo((570, 700)); pen.lineTo((50, 700)); pen.closePath()
            else:
                for char in CHARS:
                    base = base_for_char[char]
                    if glyph_name == base:
                        paths_to_commands(variants[char][0]["contours"], cff_pen=pen)
                    elif glyph_name.startswith(base + ".alt"):
                        match = re.search(r"\.alt(\d+)$", glyph_name)
                        index = int(match.group(1)) if match else 0
                        if index < len(variants[char]): paths_to_commands(variants[char][index]["contours"], cff_pen=pen)
            char_strings[glyph_name] = pen.getCharString()
        fb.setupCFF("FederwerkHandschrift", {"FullName": "Federwerk Handschrift", "FamilyName": "Federwerk Handschrift", "Weight": "Regular"}, char_strings, {})
        fb.setupMaxp()
    feature_lines = ["feature calt {"]
    for char in CHARS:
        base = base_for_char[char]
        choices = [base] + [f"{base}.alt{i:02d}" for i in range(1, len(variants[char]))]
        for index, previous in enumerate(choices):
            replacement = choices[(index + 1) % len(choices)]
            feature_lines.append(f"  sub {previous} {base}' by {replacement};")
    feature_lines.append("} calt;")
    if any(len(variants[char]) > 1 for char in CHARS):
        try:
            addOpenTypeFeaturesFromString(fb.font, "\n".join(feature_lines))
        except Exception as exc:
            raise ValueError(f"Die Alternativformen konnten nicht eingebettet werden: {exc}") from exc
    stream = io.BytesIO()
    fb.font.save(stream)
    data = stream.getvalue()
    # Re-open our output before offering it for download.
    check = TTFont(io.BytesIO(data), recalcBBoxes=True)
    check.close()
    return data


@app.get("/")
def index():
    return render_template("index.html", chars=CHARS, page_count=PAGE_COUNT, page_groups=PAGE_GROUPS)


@app.get("/api/template.pdf")
def template():
    return send_file(io.BytesIO(make_template_pdf()), mimetype="application/pdf", as_attachment=True, download_name="federwerk-schreibvorlage.pdf")


@app.post("/api/scan")
def scan():
    files = request.files.getlist("files")
    page_numbers = request.form.getlist("page_numbers")
    if len(page_numbers) != len(files):
        return jsonify(error="Wähle für jedes Bild die passende Vorlagenseite aus."), 400
    try:
        selected_pages = [int(number) for number in page_numbers]
    except ValueError:
        return jsonify(error="Ungültige Vorlagenseite."), 400
    if any(page < 0 or page >= PAGE_COUNT for page in selected_pages):
        return jsonify(error="Die ausgewählte Vorlagenseite ist ungültig."), 400
    if len(set(selected_pages)) != len(selected_pages):
        return jsonify(error="Jede Vorlagenseite darf nur einmal hochgeladen werden."), 400
    if not files:
        return jsonify(error="Bitte lade beide Seiten der ausgefüllten Vorlage als PNG, JPG oder WebP hoch."), 400
    if set(selected_pages) != set(range(PAGE_COUNT)):
        return jsonify(error=f"Lade alle {PAGE_COUNT} Seiten deiner Vorlage hoch, damit alle Groß- und Kleinbuchstaben, Umlaute, Zahlen und Sonderzeichen im Font enthalten sind."), 400
    if any(not f.filename for f in files):
        return jsonify(error="Bitte lade beide Seiten der ausgefüllten Vorlage als PNG, JPG oder WebP hoch."), 400
    if len(files) > PAGE_COUNT:
        return jsonify(error=f"Die Vorlage hat {PAGE_COUNT} Seiten. Lade höchstens ein Bild pro Vorlagenseite hoch."), 400
    session_glyphs = {char: {"char": char, "sourceChar": char, "variants": []} for char in CHARS}
    diagnostics, total_cells, detected = [], 0, 0
    for file_index, file in enumerate(files):
        page_no = selected_pages[file_index]
        raw = file.read(18 * 1024 * 1024 + 1)
        if len(raw) == 0:
            return jsonify(error=f"{file.filename}: Das Bild ist leer. Bitte wähle ein lesbares Foto aus."), 400
        if len(raw) > 18 * 1024 * 1024:
            return jsonify(error="Ein Bild ist zu groß (maximal 18 MB pro Bild)."), 413
        image = cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            return jsonify(error=f"{file.filename}: Bild nicht lesbar. Bitte PNG, JPG oder WebP verwenden."), 415
        if image.shape[0] * image.shape[1] > 26_000_000:
            return jsonify(error=f"{file.filename}: Bildauflösung zu hoch. Bitte auf maximal 26 Megapixel verkleinern."), 413
        page = straighten(image)
        if cv2.countNonZero(cv2.threshold(cv2.cvtColor(page, cv2.COLOR_BGR2GRAY), 224, 255, cv2.THRESH_BINARY_INV)[1]) < page.shape[0] * page.shape[1] * 0.00012:
            return jsonify(error=f"Seite {page_no + 1} enthält keine gut erkennbaren dunklen Schriftzüge. Fotografiere deine handschriftlich ausgefüllte Vorlage noch einmal bei gutem Licht."), 422
        page_chars = page_glyphs(page_no)
        count = len(page_chars)
        page_detected = 0
        for local in range(count):
            char = page_chars[local]
            _, row, col = layout(local, page_no)
            total_cells += 3
            for variant in range(3):
                result = trace_cell(page, cell_box(local, variant, page_no), char)
                if result and len(session_glyphs[char]["variants"]) < 3:
                    session_glyphs[char]["variants"].append(result)
                    detected += 1
                    page_detected += 1
        diagnostics.append({"file": file.filename, "page": page_no + 1, "detected": page_detected, "cells": count * 3})
    token = secrets.token_urlsafe(18)
    now = time.monotonic()
    prune_samples(now)
    while len(SAMPLES) >= SAMPLE_LIMIT:
        oldest = min(SAMPLES, key=lambda key: SAMPLES[key]["created"])
        SAMPLES.pop(oldest, None)
    SAMPLES[token] = {"glyphs": session_glyphs, "created": now}
    return jsonify(id=token, glyphs=list(session_glyphs.values()), detected=detected, total=total_cells, pages=diagnostics, chars=len(CHARS), pageCount=PAGE_COUNT, pagesConfig=[{"number": i + 1, "chars": len(group)} for i, group in enumerate(PAGE_GROUPS)], previewUrl=f"/api/font/{token}.ttf")


@app.post("/api/glyph/trace")
def trace_glyph():
    session = get_sample(request.form.get("id"))
    if not session:
        return jsonify(error="Die Sitzung ist abgelaufen. Bitte scanne deine Vorlage erneut."), 410
    char = request.form.get("char")
    if len(char or "") != 1 or char not in session["glyphs"]:
        return jsonify(error="Das ausgewählte Schriftzeichen ist ungültig."), 400
    glyph = session["glyphs"][char]
    if len(glyph["variants"]) >= 3:
        return jsonify(error="Für dieses Zeichen sind bereits drei Proben vorhanden."), 422
    upload = request.files.get("image")
    if upload is None or not upload.filename:
        return jsonify(error="Zeichne zuerst einen Buchstaben auf der Zeichenfläche."), 400
    raw = upload.read(2 * 1024 * 1024 + 1)
    if not raw or len(raw) > 2 * 1024 * 1024:
        return jsonify(error="Die Zeichnung konnte nicht gelesen werden. Bitte zeichne das Zeichen erneut."), 413
    image = cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        return jsonify(error="Die Zeichnung ist ungültig. Bitte zeichne das Zeichen erneut."), 415
    if image.shape[0] > 1000 or image.shape[1] > 2000:
        return jsonify(error="Die Zeichnung ist zu groß. Bitte versuche es erneut."), 413
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    result = trace_ink(cv2.threshold(gray, 188, 255, cv2.THRESH_BINARY_INV)[1], char)
    if result is None:
        return jsonify(error="Der Buchstabe ist kaum zu erkennen. Zeichne ihn etwas größer und mit dunklerer Linie."), 422
    glyph["variants"].append(result)
    return jsonify(glyph=result, variants=glyph["variants"], variantCount=len(glyph["variants"]))


@app.get("/api/font/<token>.<flavor>")
def font_preview(token: str, flavor: str):
    if flavor not in ("ttf", "otf"):
        abort(404)
    session = get_sample(token)
    if not session:
        abort(404)
    try:
        data = build_font(list(session["glyphs"].values()), flavor)
    except ValueError as exc:
        return str(exc), 422, {"Content-Type": "text/plain; charset=utf-8"}
    return send_file(io.BytesIO(data), mimetype="font/ttf" if flavor == "ttf" else "font/otf", as_attachment=False, download_name=f"federwerk-handschrift.{flavor}", max_age=0)


@app.post("/api/export")
def export():
    body = request.get_json(silent=True) or {}
    flavor = body.get("format")
    if flavor not in ("ttf", "otf"):
        return jsonify(error="Unbekanntes Fontformat."), 400
    token = body.get("id")
    session = get_sample(token)
    if not session:
        return jsonify(error="Die Sitzung ist abgelaufen. Bitte scanne deine Vorlage erneut."), 410
    glyphs = body.get("glyphs")
    if not isinstance(glyphs, list) or len(glyphs) > len(CHARS):
        return jsonify(error="Ungültige Zeichenzuordnung."), 400
    try:
        data = build_font(glyphs, flavor)
    except ValueError as exc:
        return jsonify(error=str(exc)), 422
    return send_file(io.BytesIO(data), mimetype="font/ttf" if flavor == "ttf" else "font/otf", as_attachment=True, download_name=f"federwerk-handschrift.{flavor}", max_age=0)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(__import__("os").environ.get("PORT", "5000")), debug=False)
