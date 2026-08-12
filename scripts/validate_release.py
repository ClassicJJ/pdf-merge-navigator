from __future__ import annotations

import argparse
import sys
from hashlib import sha256
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

import pefile
import pypdfium2 as pdfium
from pypdf import PdfReader, PdfWriter
from pypdf.annotations import Link
from pypdf.generic import ArrayObject, Fit, NameObject
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from pdf_merge_tool.core import MergeDocument, _font_name, merge_pdfs


def _hash(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _make_source(
    path: Path,
    labels: list[str],
    page_size: tuple[float, float] = A4,
) -> None:
    font_name = _font_name()
    pdf = canvas.Canvas(str(path), pagesize=page_size)
    page_height = page_size[1]
    for index, label in enumerate(labels, start=1):
        pdf.setFont(font_name, 24)
        pdf.drawString(60, page_height - 140, label)
        pdf.setFont(font_name, 12)
        pdf.drawString(60, page_height - 170, f"真实验证页 {index}")
        pdf.showPage()
    pdf.save()


def _add_internal_link(source: Path) -> None:
    reader = PdfReader(source)
    writer = PdfWriter()
    writer.append(reader)
    annotation = writer.add_annotation(
        page_number=0,
        annotation=Link(
            rect=(50, 640, 260, 720),
            target_page_index=1,
            fit=Fit.fit(),
        ),
    )
    target_page = writer.pages[1].indirect_reference
    if target_page is None:
        raise AssertionError("source link target page has no reference")
    annotation[NameObject("/Dest")] = ArrayObject(
        [target_page, NameObject("/Fit")]
    )
    temporary = source.with_name(f"{source.stem}-linked.pdf")
    with temporary.open("wb") as stream:
        writer.write(stream)
    writer.close()
    temporary.replace(source)


def _target_page(reader: PdfReader, annotation: object) -> int:
    destination = annotation.get_object()["/Dest"]
    target = destination[0]
    for index, page in enumerate(reader.pages):
        if page.indirect_reference == target:
            return index
    raise AssertionError("link target is not an output page")


def _render_pages(pdf_path: Path, output_dir: Path, count: int) -> None:
    document = pdfium.PdfDocument(str(pdf_path))
    try:
        for page_index in range(min(count, len(document))):
            page = document[page_index]
            bitmap = page.render(scale=1.6)
            image = bitmap.to_pil().convert("RGB")
            image.save(
                output_dir / f"validation-page-{page_index + 1:02d}.png"
            )
            bitmap.close()
            page.close()
    finally:
        document.close()


def _capture_ui(paths: list[Path], output_path: Path) -> None:
    from tkinter import Tk

    from PIL import ImageGrab

    from pdf_merge_tool.app import PdfMergeApp, enable_high_dpi

    enable_high_dpi()
    root = Tk()
    root.geometry("1080x720+40+40")
    app = PdfMergeApp(root)
    app.add_paths(paths)
    for uid in app.document_tree.get_children():
        values = list(app.document_tree.item(uid, "values"))
        values[3] = r"C:\PDF Samples"
        app.document_tree.item(uid, values=values)
    root.attributes("-topmost", True)
    root.update()
    left = root.winfo_rootx()
    top = root.winfo_rooty()
    right = left + root.winfo_width()
    bottom = top + root.winfo_height()
    ImageGrab.grab(
        bbox=(left, top, right, bottom),
        all_screens=True,
    ).save(output_path)
    root.destroy()


def validate(exe_path: Path | None, capture_ui: bool) -> None:
    source_dir = PROJECT_ROOT / "tmp" / "pdfs" / "release-validation"
    output_dir = PROJECT_ROOT / "output" / "pdf"
    source_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    market = source_dir / "01_市场概览.pdf"
    plan = source_dir / "02_项目计划.pdf"
    market_title = (
        "2026-07-22-Example Research Report - Quarterly Software "
        "Outlook - Long English Title Validation"
    )
    result_path = output_dir / "validation-merged.pdf"

    _make_source(market, ["市场概览：第一页", "市场概览：第二页"])
    _add_internal_link(market)
    _make_source(
        plan,
        ["项目计划：唯一页面"],
        page_size=(2480, 3508),
    )
    before = (_hash(market), _hash(plan))

    result = merge_pdfs(
        [
            MergeDocument(plan),
            MergeDocument(market, title=market_title),
        ],
        result_path,
    )

    if before != (_hash(market), _hash(plan)):
        raise AssertionError("a source PDF changed during merge")
    reader = PdfReader(result_path)
    if len(reader.pages) != 6:
        raise AssertionError(f"unexpected page count: {len(reader.pages)}")
    if result.title_page_indices != (1, 3):
        raise AssertionError(
            f"unexpected title destinations: {result.title_page_indices}"
        )
    for page in reader.pages:
        if (
            abs(float(page.mediabox.width) - A4[0]) > 0.01
            or abs(float(page.mediabox.height) - A4[1]) > 0.01
        ):
            raise AssertionError("output page is not portrait A4")
    navigation = reader.pages[0]
    navigation_text = navigation.extract_text() or ""
    expected_navigation_text = (
        "序号",
        "文件名称",
        "01",
        "02",
    )
    if any(text not in navigation_text for text in expected_navigation_text):
        raise AssertionError("navigation text is missing")
    if any(
        text in navigation_text
        for text in ("本文档共包含", "总导航", "PDF MERGE")
    ):
        raise AssertionError("obsolete navigation text remains")
    navigation_targets = [
        _target_page(reader, annotation)
        for annotation in navigation.get("/Annots", [])
    ]
    if navigation_targets != [1, 3]:
        raise AssertionError(
            f"unexpected navigation link targets: {navigation_targets}"
        )
    source_link = reader.pages[4]["/Annots"][0]
    if _target_page(reader, source_link) != 5:
        raise AssertionError("source internal link was not preserved")
    page_texts = [page.extract_text() or "" for page in reader.pages]
    expected_text = (
        (1, "文件名称："),
        (1, "项目计划"),
        (2, "项目计划：唯一页面"),
        (3, "文件名称："),
        (3, "2026-07-22-Example Research Report"),
        (3, "Long English"),
        (3, "Title Validation"),
        (4, "市场概览：第一页"),
        (5, "市场概览：第二页"),
    )
    for page_index, text in expected_text:
        if text not in page_texts[page_index]:
            raise AssertionError(
                f"missing expected text on page {page_index + 1}: {text}"
            )
    _render_pages(result_path, output_dir, count=4)
    if capture_ui:
        _capture_ui([plan, market], output_dir / "validation-ui.png")

    if exe_path is not None:
        if not exe_path.exists():
            raise AssertionError(f"EXE not found: {exe_path}")
        executable = pefile.PE(str(exe_path), fast_load=True)
        try:
            if executable.OPTIONAL_HEADER.Subsystem != 2:
                raise AssertionError(
                    "EXE is not using the Windows GUI subsystem"
                )
            executable.parse_data_directories(
                directories=[
                    pefile.DIRECTORY_ENTRY[
                        "IMAGE_DIRECTORY_ENTRY_RESOURCE"
                    ]
                ]
            )
            resources = getattr(
                executable,
                "DIRECTORY_ENTRY_RESOURCE",
                None,
            )
            resource_types = (
                {entry.id for entry in resources.entries}
                if resources is not None
                else set()
            )
            if not {3, 14}.issubset(resource_types):
                raise AssertionError(
                    "EXE is missing Windows icon resources"
                )
        finally:
            executable.close()

    print(
        "Release validation passed: 2 source PDFs, 6 output pages, "
        "all pages A4, 2 navigation links, 1 preserved source link, "
        "Chinese text and "
        f"{min(4, len(reader.pages))} rendered previews."
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--exe", type=Path)
    parser.add_argument("--capture-ui", action="store_true")
    arguments = parser.parse_args()
    validate(arguments.exe, arguments.capture_ui)


if __name__ == "__main__":
    main()
