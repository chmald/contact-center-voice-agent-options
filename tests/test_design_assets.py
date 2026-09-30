"""Structural guards for the generated documentation assets (no GUI required)."""

from __future__ import annotations

from html import unescape
from html.parser import HTMLParser
import re
import runpy
import struct
from urllib.parse import unquote, urlsplit
import xml.etree.ElementTree as ET

import pytest


ASSET_ROOT = "docs/assets"
DIAGRAM_SOURCE = "voice-live-vs-realtime-api-architecture.drawio"
PAGES = (
    ("arch", "1 - Solution architecture", "01-solution-architecture.png"),
    ("ways", "2 - Three ways to connect", "02-three-ways-to-connect.png"),
    ("call", "3 - Phone call flow", "03-phone-call-flow.png"),
    ("deploy", "4 - Deployment and regions", "04-deployment-and-regions.png"),
)


@pytest.fixture
def diagram_generator(repo_root):
    return runpy.run_path(str(repo_root / "scripts" / "build-diagrams.py"))


@pytest.fixture
def diagram_xml(diagram_generator):
    return ET.fromstring(diagram_generator["build"]())


class HtmlContent(HTMLParser):
    def __init__(self):
        super().__init__()
        self.text = []
        self.links = []

    def handle_data(self, data):
        self.text.append(data)

    def handle_starttag(self, tag, attrs):
        for name, value in attrs:
            if value and ((tag == "a" and name == "href") or (tag == "img" and name == "src")):
                self.links.append(value)


def _label(cell):
    parser = HtmlContent()
    parser.feed(cell.get("value", ""))
    return unescape("".join(parser.text))


def _bounds(cell):
    geometry = cell.find("mxGeometry")
    assert geometry is not None
    return tuple(float(geometry.get(key, "0")) for key in ("x", "y", "width", "height"))


def test_committed_diagram_matches_deterministic_generator(repo_root, diagram_generator):
    generated = diagram_generator["build"]()
    assert generated == diagram_generator["build"]()
    source = repo_root / ASSET_ROOT / DIAGRAM_SOURCE
    assert source.read_text(encoding="utf-8") == generated, "Run scripts/build-diagrams.py and re-export the PNGs"


def test_diagram_pages_ids_edges_and_bounds(diagram_xml):
    assert [(page.get("id"), page.get("name")) for page in diagram_xml] == [
        (page_id, title) for page_id, title, _ in PAGES
    ]
    for page in diagram_xml:
        model = page.find("mxGraphModel")
        assert model is not None
        width, height = float(model.get("pageWidth")), float(model.get("pageHeight"))
        cells = model.findall("./root/mxCell")
        ids = {cell.get("id") for cell in cells}
        assert len(ids) == len(cells)
        for cell in cells:
            if cell.get("parent"):
                assert cell.get("parent") in ids
            if cell.get("edge") == "1":
                assert cell.get("source") in ids and cell.get("target") in ids
            geometry = cell.find("mxGeometry")
            if cell.get("vertex") == "1" and geometry is not None and geometry.get("relative") != "1":
                x, y, w, h = _bounds(cell)
                assert x >= 0 and y >= 0 and w > 0 and h > 0
                assert x + w <= width and y + h <= height, (page.get("name"), _label(cell))


def test_search_is_outside_foundry_with_app_side_rag_edge(diagram_xml):
    page = diagram_xml.find("./diagram[@id='arch']")
    cells = page.findall(".//mxCell")
    foundry = next(cell for cell in cells if _label(cell).startswith("ONE Foundry resource"))
    search = next(cell for cell in cells if _label(cell).startswith("Azure AI Search"))
    rag = next(cell for cell in cells if _label(cell).startswith("Shared RAG tool"))
    fx, fy, fw, fh = _bounds(foundry)
    sx, sy, sw, sh = _bounds(search)
    assert sx + sw <= fx or fx + fw <= sx or sy + sh <= fy or fy + fh <= sy
    assert any(cell.get("source") == rag.get("id") and cell.get("target") == search.get("id") for cell in cells)


def test_connection_labels_preserve_routes_and_wrapping(diagram_xml):
    cells = diagram_xml.find("./diagram[@id='ways']").findall(".//mxCell")
    endpoints = [cell for cell in cells if _label(cell).startswith("wss://")]
    assert len(endpoints) == 3
    for cell in endpoints:
        assert "<br>" in cell.get("value", "")
        assert _bounds(cell)[3] >= 150
    labels = "\n".join(_label(cell) for cell in cells)
    for required in (
        "/voice-live/realtime?api-version=",
        "/openai/v1/realtime?model=<deployment>",
        "/api/projects/<p>/agents/<a>/endpoint/protocols/voice?api-version=",
        "Foundry-Features:", "VoiceAgents=V1Preview", "PREVIEW",
        "ACS", "Twilio", "Asterisk", "per-app admission",
    ):
        assert required in labels


def test_png_exports_exist_and_are_valid_images(repo_root):
    for _, _, filename in PAGES:
        data = (repo_root / ASSET_ROOT / "diagrams" / filename).read_bytes()
        assert data[:8] == b"\x89PNG\r\n\x1a\n"
        width, height = struct.unpack(">II", data[16:24])
        assert width > 1000 and height > 500


def test_comparison_pdf_is_one_page_without_local_file_urls(repo_root):
    # Edge exports uncompressed page dictionaries; no optional PDF library needed.
    data = (repo_root / ASSET_ROOT / "comparison-one-pager.pdf").read_bytes()
    assert data.startswith(b"%PDF-")
    assert len(re.findall(rb"/Type\s*/Page\b", data)) == 1
    assert b"file:///" not in data


def test_documentation_asset_links_resolve(repo_root):
    documents = [repo_root / "README.md", *sorted((repo_root / "docs").glob("*.md"))]
    references = []
    for path in documents:
        text = path.read_text(encoding="utf-8")
        references.extend((path, target) for target in re.findall(r"!?\[[^\]\n]*\]\(([^)\s]+)\)", text))
    html_path = repo_root / ASSET_ROOT / "comparison-one-pager.html"
    parser = HtmlContent()
    parser.feed(html_path.read_text(encoding="utf-8"))
    references.extend((html_path, target) for target in parser.links)
    asset_targets = set()
    for document, target in references:
        url = urlsplit(target)
        if url.scheme or url.netloc or not url.path:
            continue
        resolved = (document.parent / unquote(url.path).replace("\\", "/")).resolve()
        assert resolved.exists(), f"{document.name}: missing {target}"
        if resolved.is_relative_to(repo_root / ASSET_ROOT):
            asset_targets.add(resolved.name)
    assert {DIAGRAM_SOURCE, "comparison-one-pager.html", "comparison-one-pager.pdf"} <= asset_targets
    assert {filename for _, _, filename in PAGES} <= asset_targets