from __future__ import annotations

from hashlib import sha256
from pathlib import Path

import pytest
from pypdf import PdfReader, PdfWriter
from pypdf.annotations import Link
from pypdf.generic import ArrayObject, Fit, NameObject
from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfgen import canvas

from pdf_merge_tool.core import (
    MergeDocument,
    PAGE_MARGIN,
    PdfMergeError,
    TABLE_SERIAL_WIDTH,
    inspect_pdf,
    merge_pdfs,
)


def _make_pdf(path: Path, labels: list[str]) -> None:
    pdf = canvas.Canvas(str(path), pagesize=(300, 400))
    for label in labels:
        pdf.setFont("Helvetica", 18)
        pdf.drawString(30, 200, label)
        pdf.showPage()
    pdf.save()


def _make_linked_pdf(path: Path) -> None:
    plain = path.with_name(f"{path.stem}-plain.pdf")
    _make_pdf(plain, ["linked first", "linked second"])
    writer = PdfWriter()
    writer.append(plain)
    annotation = writer.add_annotation(
        page_number=0,
        annotation=Link(
            rect=(20, 180, 180, 230),
            target_page_index=1,
            fit=Fit.fit(),
        ),
    )
    target_page = writer.pages[1].indirect_reference
    assert target_page is not None
    annotation[NameObject("/Dest")] = ArrayObject(
        [target_page, NameObject("/Fit")]
    )
    with path.open("wb") as stream:
        writer.write(stream)
    writer.close()
    plain.unlink()


def _annotation_target_page(reader: PdfReader, annotation: object) -> int:
    destination = annotation.get_object()["/Dest"]
    target_reference = destination[0]
    for index, page in enumerate(reader.pages):
        if page.indirect_reference == target_reference:
            return index
    raise AssertionError("link target is not a page in the output")


def _file_hash(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def test_merge_builds_navigation_titles_and_preserves_order(
    tmp_path: Path,
) -> None:
    first = tmp_path / "第一份.pdf"
    second = tmp_path / "Second.pdf"
    output = tmp_path / "合并结果.pdf"
    _make_pdf(first, ["FIRST-1", "FIRST-2"])
    _make_pdf(second, ["SECOND-1"])
    source_hashes = (_file_hash(first), _file_hash(second))
    updates: list[tuple[int, int, str]] = []

    result = merge_pdfs(
        [
            MergeDocument(second),
            MergeDocument(first, title="中文自定义标题"),
        ],
        output,
        progress=lambda current, total, title: updates.append(
            (current, total, title)
        ),
    )

    reader = PdfReader(output)
    assert result.document_count == 2
    assert result.navigation_page_count == 1
    assert result.title_page_indices == (1, 3)
    assert result.total_page_count == 6
    assert len(reader.pages) == 6
    assert all(
        float(page.mediabox.width) == pytest.approx(A4[0])
        and float(page.mediabox.height) == pytest.approx(A4[1])
        for page in reader.pages
    )
    navigation_text = reader.pages[0].extract_text() or ""
    assert "本文档共包含" not in navigation_text
    assert "序号" in navigation_text
    assert "文件名称" in navigation_text
    assert "01" in navigation_text
    assert "02" in navigation_text
    assert "总导航" not in navigation_text
    assert "PDF MERGE" not in navigation_text
    first_title_text = reader.pages[1].extract_text() or ""
    assert "文件名称：" in first_title_text
    assert "Second" in first_title_text
    assert "DOCUMENT" not in first_title_text
    assert "第 1 份" not in first_title_text
    assert "SECOND-1" in (reader.pages[2].extract_text() or "")
    second_title_text = reader.pages[3].extract_text() or ""
    assert "文件名称：" in second_title_text
    assert "中文自定义标题" in second_title_text
    assert "FIRST-1" in (reader.pages[4].extract_text() or "")
    assert "FIRST-2" in (reader.pages[5].extract_text() or "")
    annotations = [
        item.get_object() for item in reader.pages[0]["/Annots"]
    ]
    assert [_annotation_target_page(reader, item) for item in annotations] == [
        1,
        3,
    ]
    assert updates == [(1, 2, "Second"), (2, 2, "中文自定义标题")]
    assert (_file_hash(first), _file_hash(second)) == source_hashes


def test_navigation_serial_column_is_narrow_and_centered(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.pdf"
    output = tmp_path / "output.pdf"
    _make_pdf(source, ["SOURCE"])
    centered: list[tuple[float, str]] = []
    original = canvas.Canvas.drawCentredString

    def record_centered(
        pdf: canvas.Canvas,
        x: float,
        y: float,
        text: str,
        *args: object,
        **kwargs: object,
    ) -> None:
        if text in {"序号", "01"}:
            centered.append((x, text))
        original(pdf, x, y, text, *args, **kwargs)

    monkeypatch.setattr(
        canvas.Canvas,
        "drawCentredString",
        record_centered,
    )

    merge_pdfs([MergeDocument(source)], output)

    expected_center = PAGE_MARGIN + TABLE_SERIAL_WIDTH / 2
    assert TABLE_SERIAL_WIDTH == 48
    assert centered == [
        (expected_center, "序号"),
        (expected_center, "01"),
    ]


def test_merge_preserves_internal_links_inside_source_pdf(
    tmp_path: Path,
) -> None:
    source = tmp_path / "linked.pdf"
    output = tmp_path / "linked-merged.pdf"
    _make_linked_pdf(source)

    merge_pdfs([MergeDocument(source)], output)

    reader = PdfReader(output)
    source_first_page = 2
    annotation = reader.pages[source_first_page]["/Annots"][0]
    assert _annotation_target_page(reader, annotation) == 3


def test_large_and_rotated_source_pages_fit_a4_without_source_changes(
    tmp_path: Path,
) -> None:
    huge = tmp_path / "超大专利.pdf"
    huge_pdf = canvas.Canvas(str(huge), pagesize=(2480, 3508))
    huge_pdf.setFont("Helvetica", 72)
    huge_pdf.drawString(100, 1754, "HUGE-PATENT")
    huge_pdf.rect(40, 40, 2400, 3428)
    huge_pdf.showPage()
    huge_pdf.save()

    portrait = tmp_path / "rotated-plain.pdf"
    _make_pdf(portrait, ["ROTATED-LANDSCAPE"])
    rotated = tmp_path / "横向文件.pdf"
    rotated_writer = PdfWriter()
    rotated_writer.add_page(PdfReader(portrait).pages[0].rotate(90))
    with rotated.open("wb") as stream:
        rotated_writer.write(stream)
    rotated_writer.close()
    portrait.unlink()
    source_hashes = (_file_hash(huge), _file_hash(rotated))
    output = tmp_path / "A4-output.pdf"

    merge_pdfs(
        [MergeDocument(huge), MergeDocument(rotated)],
        output,
    )

    reader = PdfReader(output)
    huge_page = reader.pages[2]
    rotated_page = reader.pages[4]
    assert float(huge_page.mediabox.width) == pytest.approx(A4[0])
    assert float(huge_page.mediabox.height) == pytest.approx(A4[1])
    assert float(rotated_page.mediabox.width) == pytest.approx(
        landscape(A4)[0]
    )
    assert float(rotated_page.mediabox.height) == pytest.approx(
        landscape(A4)[1]
    )
    assert huge_page.rotation == 0
    assert rotated_page.rotation == 0
    assert "HUGE-PATENT" in (huge_page.extract_text() or "")
    assert "ROTATED-LANDSCAPE" in (
        rotated_page.extract_text() or ""
    )
    assert (_file_hash(huge), _file_hash(rotated)) == source_hashes


def test_long_navigation_uses_multiple_front_pages_with_working_links(
    tmp_path: Path,
) -> None:
    documents: list[MergeDocument] = []
    for index in range(28):
        source = tmp_path / f"{index:02d}-测试文档.pdf"
        _make_pdf(source, [f"DOC-{index:02d}"])
        documents.append(
            MergeDocument(
                source,
                title=f"{index + 1:02d} 很长的中文文档名称用于验证导航自动分页",
            )
        )
    output = tmp_path / "many.pdf"

    result = merge_pdfs(documents, output)

    reader = PdfReader(output)
    assert result.navigation_page_count >= 2
    annotation_count = 0
    targets: list[int] = []
    for page_index in range(result.navigation_page_count):
        page_text = reader.pages[page_index].extract_text() or ""
        assert "本文档共包含" not in page_text
        assert "序号" in page_text
        assert "文件名称" in page_text
        for annotation in reader.pages[page_index].get("/Annots", []):
            annotation_count += 1
            targets.append(_annotation_target_page(reader, annotation))
    assert annotation_count == len(documents)
    assert targets == list(result.title_page_indices)


def test_inspect_and_merge_report_user_facing_input_errors(
    tmp_path: Path,
) -> None:
    missing = tmp_path / "missing.pdf"
    with pytest.raises(PdfMergeError, match="找不到"):
        inspect_pdf(missing)

    source = tmp_path / "source.pdf"
    _make_pdf(source, ["only"])
    with pytest.raises(PdfMergeError, match="不能与任一源"):
        merge_pdfs([MergeDocument(source)], source)
    with pytest.raises(PdfMergeError, match="至少添加"):
        merge_pdfs([], tmp_path / "output.pdf")
