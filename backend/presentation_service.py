"""
presentation_service.py
───────────────────────
Turns an uploaded .pptx into something the browser can present faithfully.

Why not render .pptx in the browser?
  Client-side PPTX renderers re-implement PowerPoint's layout engine and
  get fonts (especially Sinhala/Tamil shaping), SmartArt, charts and effects
  visibly wrong. For a live event the slides must look exactly as authored.

Strategy (hybrid):
  1. Slides → PDF using the real PowerPoint installed on the event laptop,
     driven through COM automation (pywin32). Pixel-identical to PowerPoint.
     Fallback: LibreOffice headless (`soffice --convert-to pdf`) if
     PowerPoint is not installed. The PDF is rendered by pdf.js in the
     frontend as crisp vector graphics at any screen size.
  2. Media → a PDF can't carry video, so we open the .pptx (a ZIP of XML)
     ourselves, find every embedded video/audio shape, extract the media
     file, and compute its exact on-slide rectangle (including group-shape
     transforms and placeholder inheritance). The frontend overlays a real
     <video>/<audio> element on top of the rendered slide at that spot.
     Start mode (automatic vs on click), looping, volume and "play full
     screen" are read from the slide's timing/media XML.

Results are cached per file content hash in PRESENTATIONS_DIR, so loading
the same deck again (e.g. after a browser refresh) is instant.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import posixpath
import re
import shutil
import subprocess
import tempfile
import threading
import zipfile
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree as ET

log = logging.getLogger("presentations")

PRESENTATIONS_DIR = Path(
    os.getenv("PRESENTATIONS_DIR", Path(__file__).parent / ".presentations")
).resolve()
MAX_UPLOAD_BYTES = int(os.getenv("MAX_PRESENTATION_MB", "1024")) * 1024 * 1024

ID_PATTERN = re.compile(r"^[0-9a-f]{20}$")
MEDIA_NAME_PATTERN = re.compile(r"^[\w.\-]+$")

NS = {
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "p14": "http://schemas.microsoft.com/office/powerpoint/2010/main",
    "rel": "http://schemas.openxmlformats.org/package/2006/relationships",
}
R_EMBED = f"{{{NS['r']}}}embed"
R_LINK = f"{{{NS['r']}}}link"
R_ID = f"{{{NS['r']}}}id"

MIME_TYPES = {
    ".mp4": "video/mp4", ".m4v": "video/mp4", ".mov": "video/quicktime",
    ".webm": "video/webm", ".ogv": "video/ogg", ".ogg": "audio/ogg",
    ".wmv": "video/x-ms-wmv", ".avi": "video/x-msvideo", ".mpg": "video/mpeg",
    ".mpeg": "video/mpeg", ".mkv": "video/x-matroska",
    ".mp3": "audio/mpeg", ".m4a": "audio/mp4", ".wav": "audio/wav",
    ".wma": "audio/x-ms-wma", ".aac": "audio/aac",
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".gif": "image/gif", ".bmp": "image/bmp",
}

CONVERSION_TIMEOUT_S = int(os.getenv("PRESENTATION_CONVERSION_TIMEOUT", "300"))

_convert_lock = threading.Lock()


class PresentationError(Exception):
    """Operator-facing error (message is shown in the UI)."""


# ── Storage helpers ─────────────────────────────────────────────────────────
def presentation_dir(presentation_id: str) -> Path:
    if not ID_PATTERN.match(presentation_id):
        raise PresentationError("Invalid presentation id")
    return PRESENTATIONS_DIR / presentation_id


def media_path(presentation_id: str, name: str) -> Path:
    if not MEDIA_NAME_PATTERN.match(name):
        raise PresentationError("Invalid media name")
    return presentation_dir(presentation_id) / "media" / name


def pdf_path(presentation_id: str) -> Path:
    return presentation_dir(presentation_id) / "slides.pdf"


def delete_presentation(presentation_id: str) -> None:
    shutil.rmtree(presentation_dir(presentation_id), ignore_errors=True)


def load_manifest(presentation_id: str) -> dict | None:
    manifest_file = presentation_dir(presentation_id) / "manifest.json"
    if manifest_file.exists():
        return json.loads(manifest_file.read_text(encoding="utf-8"))
    return None


def hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()[:20]


# ── Public entry point (blocking; call via asyncio.to_thread) ───────────────
def process_pptx(upload: Path, original_name: str) -> dict:
    if not zipfile.is_zipfile(upload):
        raise PresentationError("This file is not a valid .pptx presentation.")

    presentation_id = hash_file(upload)
    cached = load_manifest(presentation_id)
    if cached and pdf_path(presentation_id).exists():
        upload.unlink(missing_ok=True)
        return cached

    target = presentation_dir(presentation_id)
    shutil.rmtree(target, ignore_errors=True)
    (target / "media").mkdir(parents=True)
    source = target / "source.pptx"
    shutil.move(str(upload), source)

    try:
        converter = convert_to_pdf(source, target / "slides.pdf")
        width, height, slides = extract_slides(source, target / "media", presentation_id)
    except Exception:
        shutil.rmtree(target, ignore_errors=True)
        raise

    manifest = {
        "id": presentation_id,
        "name": original_name,
        "converter": converter,
        "pdfUrl": f"/api/presentations/{presentation_id}/slides.pdf",
        "slideWidth": width,
        "slideHeight": height,
        "slides": slides,
    }
    (target / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    source.unlink(missing_ok=True)
    return manifest


# ── PPTX → PDF ──────────────────────────────────────────────────────────────
def convert_to_pdf(source: Path, output: Path) -> str:
    errors: list[str] = []
    with _convert_lock:
        if os.name == "nt":
            try:
                _convert_with_powerpoint(source, output)
                return "powerpoint"
            except Exception as exc:
                log.warning("PowerPoint conversion failed: %s", exc)
                errors.append(f"PowerPoint: {exc}")

        soffice = _find_libreoffice()
        if soffice:
            try:
                _convert_with_libreoffice(soffice, source, output)
                return "libreoffice"
            except Exception as exc:
                log.warning("LibreOffice conversion failed: %s", exc)
                errors.append(f"LibreOffice: {exc}")
        else:
            errors.append("LibreOffice: not installed")

    raise PresentationError(
        "Could not convert the .pptx. Install Microsoft PowerPoint or LibreOffice "
        "on this laptop, or load a PDF export instead. (" + "; ".join(errors) + ")"
    )


def _convert_with_powerpoint(source: Path, output: Path) -> None:
    import pythoncom
    import win32com.client

    PP_SAVE_AS_PDF = 32
    MSO_TRUE, MSO_FALSE = -1, 0

    pythoncom.CoInitialize()
    try:
        app = win32com.client.DispatchEx("PowerPoint.Application")
        presentation = app.Presentations.Open(str(source), MSO_TRUE, MSO_FALSE, MSO_FALSE)
        try:
            presentation.SaveAs(str(output), PP_SAVE_AS_PDF)
        finally:
            presentation.Close()
            # PowerPoint is single-instance: only quit if the operator doesn't
            # have their own presentations open in it.
            if app.Presentations.Count == 0:
                app.Quit()
    finally:
        pythoncom.CoUninitialize()

    if not output.exists() or output.stat().st_size == 0:
        raise RuntimeError("PowerPoint produced no PDF output")


def _find_libreoffice() -> str | None:
    candidates = [
        os.getenv("LIBREOFFICE_PATH"),
        shutil.which("soffice"),
        r"C:\Program Files\LibreOffice\program\soffice.exe",
        r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
        "/usr/bin/soffice",
        "/Applications/LibreOffice.app/Contents/MacOS/soffice",
    ]
    return next((c for c in candidates if c and Path(c).exists()), None)


def _convert_with_libreoffice(soffice: str, source: Path, output: Path) -> None:
    with tempfile.TemporaryDirectory() as profile, tempfile.TemporaryDirectory() as outdir:
        subprocess.run(
            [
                soffice,
                f"-env:UserInstallation={Path(profile).as_uri()}",
                "--headless", "--norestore",
                "--convert-to", "pdf",
                "--outdir", outdir,
                str(source),
            ],
            check=True,
            capture_output=True,
            timeout=CONVERSION_TIMEOUT_S,
        )
        produced = Path(outdir) / (source.stem + ".pdf")
        if not produced.exists():
            raise RuntimeError("LibreOffice produced no PDF output")
        shutil.move(str(produced), output)


# ── PPTX media extraction ───────────────────────────────────────────────────
@dataclass(frozen=True)
class _Transform:
    """Maps child EMU coordinates to slide EMU coordinates: X = sx·x + tx."""
    sx: float = 1.0
    sy: float = 1.0
    tx: float = 0.0
    ty: float = 0.0

    def compose_group(self, grp_xfrm: ET.Element | None) -> "_Transform":
        if grp_xfrm is None:
            return self
        off, ext = grp_xfrm.find("a:off", NS), grp_xfrm.find("a:ext", NS)
        ch_off, ch_ext = grp_xfrm.find("a:chOff", NS), grp_xfrm.find("a:chExt", NS)
        if None in (off, ext, ch_off, ch_ext):
            return self
        ch_cx, ch_cy = int(ch_ext.get("cx", 0)), int(ch_ext.get("cy", 0))
        gsx = int(ext.get("cx", 0)) / ch_cx if ch_cx else 1.0
        gsy = int(ext.get("cy", 0)) / ch_cy if ch_cy else 1.0
        gtx = int(off.get("x", 0)) - int(ch_off.get("x", 0)) * gsx
        gty = int(off.get("y", 0)) - int(ch_off.get("y", 0)) * gsy
        return _Transform(
            sx=self.sx * gsx, sy=self.sy * gsy,
            tx=self.sx * gtx + self.tx, ty=self.sy * gty + self.ty,
        )


def _read_xml(archive: zipfile.ZipFile, name: str) -> ET.Element | None:
    try:
        return ET.fromstring(archive.read(name))
    except KeyError:
        return None


def _rels_path(part: str) -> str:
    directory, filename = posixpath.split(part)
    return posixpath.join(directory, "_rels", filename + ".rels")


def _read_rels(archive: zipfile.ZipFile, part: str) -> dict[str, dict]:
    root = _read_xml(archive, _rels_path(part))
    rels: dict[str, dict] = {}
    if root is None:
        return rels
    base = posixpath.dirname(part)
    for rel in root.findall("rel:Relationship", NS):
        external = rel.get("TargetMode") == "External"
        target = rel.get("Target", "")
        rels[rel.get("Id")] = {
            "type": rel.get("Type", ""),
            "external": external,
            "target": target if external else posixpath.normpath(posixpath.join(base, target)),
        }
    return rels


def _rel_of_type(rels: dict[str, dict], suffix: str) -> str | None:
    return next((r["target"] for r in rels.values() if r["type"].endswith(suffix)), None)


def _placeholder_xfrm(archive: zipfile.ZipFile, part: str, ph: ET.Element) -> ET.Element | None:
    """Find the xfrm a placeholder inherits from its slide layout, then master."""
    ph_idx, ph_type = ph.get("idx"), ph.get("type")
    rels = _read_rels(archive, part)
    for suffix in ("/slideLayout", "/slideMaster"):
        parent = _rel_of_type(rels, suffix)
        if not parent:
            continue
        root = _read_xml(archive, parent)
        if root is None:
            continue
        for candidate in root.iter():
            cand_ph = candidate.find("./*/p:nvPr/p:ph", NS)
            if cand_ph is None:
                continue
            if (ph_idx and cand_ph.get("idx") == ph_idx) or (ph_type and cand_ph.get("type") == ph_type):
                xfrm = candidate.find("p:spPr/a:xfrm", NS)
                if xfrm is not None:
                    return xfrm
        part, rels = parent, _read_rels(archive, parent)
    return None


def _media_timing(slide: ET.Element) -> dict[str, dict]:
    """
    Per shape id: whether its media starts automatically, loops, and its volume.
    PowerPoint encodes "Start: Automatically" as a mediacall effect that is a
    withEffect/afterEffect *before* any click in the main sequence; "On Click"
    and "In Click Sequence" are clickEffect nodes.
    """
    timing: dict[str, dict] = {}
    timing_root = slide.find("p:timing", NS)
    if timing_root is None:
        return timing

    seen_click = False
    for ctn in timing_root.iter(f"{{{NS['p']}}}cTn"):
        node_type = ctn.get("nodeType")
        if node_type == "clickEffect" and ctn.get("presetClass") != "mediacall":
            seen_click = True
        if ctn.get("presetClass") == "mediacall":
            target = ctn.find(".//p:spTgt", NS)
            if target is not None and target.get("spid") not in timing:
                automatic = node_type in ("withEffect", "afterEffect") and not seen_click
                timing[target.get("spid")] = {"autoplay": automatic}
            if node_type == "clickEffect":
                seen_click = True

    for tag in ("video", "audio"):
        for element in timing_root.iter(f"{{{NS['p']}}}{tag}"):
            media_node = element.find("p:cMediaNode", NS)
            target = media_node.find("p:tgtEl/p:spTgt", NS) if media_node is not None else None
            if target is None:
                continue
            info = timing.setdefault(target.get("spid"), {"autoplay": False})
            ctn = media_node.find("p:cTn", NS)
            info["loop"] = ctn is not None and ctn.get("repeatCount") == "indefinite"
            info["volume"] = int(media_node.get("vol", "100000")) / 100000
            info["muted"] = media_node.get("mute") in ("1", "true")
            info["fullScreen"] = element.get("fullScrn") in ("1", "true")
    return timing


def _extract_part(archive: zipfile.ZipFile, part: str, media_dir: Path, extracted: dict[str, str]) -> str:
    if part in extracted:
        return extracted[part]
    name = re.sub(r"[^\w.\-]", "_", posixpath.basename(part))
    stem, suffix = os.path.splitext(name)
    counter = 1
    while (media_dir / name).exists():
        counter += 1
        name = f"{stem}_{counter}{suffix}"
    with archive.open(part) as src, (media_dir / name).open("wb") as dst:
        shutil.copyfileobj(src, dst)
    extracted[part] = name
    return name


def extract_slides(source: Path, media_dir: Path, presentation_id: str) -> tuple[int, int, list[dict]]:
    with zipfile.ZipFile(source) as archive:
        pres = _read_xml(archive, "ppt/presentation.xml")
        if pres is None:
            raise PresentationError("This file is not a valid .pptx presentation.")

        size = pres.find("p:sldSz", NS)
        width = int(size.get("cx", 12192000)) if size is not None else 12192000
        height = int(size.get("cy", 6858000)) if size is not None else 6858000

        pres_rels = _read_rels(archive, "ppt/presentation.xml")
        slide_parts = [
            pres_rels[sld.get(R_ID)]["target"]
            for sld in pres.findall("p:sldIdLst/p:sldId", NS)
            if sld.get(R_ID) in pres_rels
        ]

        extracted: dict[str, str] = {}
        slides = []
        for number, part in enumerate(slide_parts, start=1):
            slide = _read_xml(archive, part)
            if slide is None:
                continue
            slides.append({
                "number": number,
                "hidden": slide.get("show") in ("0", "false"),
                "media": _slide_media(archive, part, slide, width, height,
                                      media_dir, presentation_id, extracted),
            })
        return width, height, slides


def _slide_media(archive, part, slide, width, height, media_dir, presentation_id, extracted) -> list[dict]:
    rels = _read_rels(archive, part)
    timing = _media_timing(slide)
    media: list[dict] = []
    tree = slide.find("p:cSld/p:spTree", NS)
    if tree is None:
        return media

    def url_for(name: str) -> str:
        return f"/api/presentations/{presentation_id}/media/{name}"

    def walk(container: ET.Element, transform: _Transform) -> None:
        for child in container:
            tag = child.tag.split("}")[-1]
            if tag == "grpSp":
                walk(child, transform.compose_group(child.find("p:grpSpPr/a:xfrm", NS)))
            elif tag == "pic":
                item = _media_item(child, transform)
                if item:
                    media.append(item)

    def _media_item(pic: ET.Element, transform: _Transform) -> dict | None:
        nv_pr = pic.find("p:nvPicPr/p:nvPr", NS)
        if nv_pr is None:
            return None
        video = nv_pr.find("a:videoFile", NS)
        audio = nv_pr.find("a:audioFile", NS)
        if audio is None:
            audio = nv_pr.find("a:wavAudioFile", NS)
        linked = video if video is not None else audio
        if linked is None:
            return None
        kind = "video" if video is not None else "audio"

        embedded = nv_pr.find(".//p14:media", NS)
        rel_id = embedded.get(R_EMBED) if embedded is not None else None
        rel_id = rel_id or linked.get(R_LINK) or linked.get(R_EMBED)
        rel = rels.get(rel_id or "")

        c_nv_pr = pic.find("p:nvPicPr/p:cNvPr", NS)
        shape_id = c_nv_pr.get("id", "") if c_nv_pr is not None else ""

        xfrm = pic.find("p:spPr/a:xfrm", NS)
        if xfrm is None:
            ph = nv_pr.find("p:ph", NS)
            xfrm = _placeholder_xfrm(archive, part, ph) if ph is not None else None
        off = xfrm.find("a:off", NS) if xfrm is not None else None
        ext = xfrm.find("a:ext", NS) if xfrm is not None else None
        x = transform.sx * int(off.get("x", 0)) + transform.tx if off is not None else 0
        y = transform.sy * int(off.get("y", 0)) + transform.ty if off is not None else 0
        w = transform.sx * int(ext.get("cx", 0)) if ext is not None else width
        h = transform.sy * int(ext.get("cy", 0)) if ext is not None else height

        item = {
            "id": f"{posixpath.basename(part)}-{shape_id}",
            "kind": kind,
            "title": c_nv_pr.get("name", kind) if c_nv_pr is not None else kind,
            "x": x / width, "y": y / height, "w": w / width, "h": h / height,
            "autoplay": False, "loop": False, "volume": 1.0, "muted": False, "fullScreen": False,
            "url": None, "mime": None, "posterUrl": None,
            "available": False, "reason": None,
        }
        item.update(timing.get(shape_id, {}))

        blip = pic.find("p:blipFill/a:blip", NS)
        poster_rel = rels.get(blip.get(R_EMBED, "")) if blip is not None else None
        if poster_rel and not poster_rel["external"] and poster_rel["target"] in archive.namelist():
            poster = _extract_part(archive, poster_rel["target"], media_dir, extracted)
            item["posterUrl"] = url_for(poster)

        if rel is None:
            item["reason"] = "Media relationship missing from the file"
        elif rel["external"]:
            target = rel["target"]
            item["reason"] = (
                "Online video (needs internet) — not embedded in the file"
                if target.startswith(("http://", "https://"))
                else "Linked media file — re-insert it as embedded in PowerPoint"
            )
        elif rel["target"] not in archive.namelist():
            item["reason"] = "Embedded media file missing from the .pptx"
        else:
            name = _extract_part(archive, rel["target"], media_dir, extracted)
            item.update(
                url=url_for(name),
                mime=MIME_TYPES.get(os.path.splitext(name)[1].lower(), "application/octet-stream"),
                available=True,
            )
        return item

    walk(tree, _Transform())
    return media
