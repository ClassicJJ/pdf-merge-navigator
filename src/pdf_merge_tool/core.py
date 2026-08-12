from __future__ import annotations

import os
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Callable, Sequence
from uuid import uuid4

from pypdf import PageObject, PdfReader, PdfWriter, Transformation
from pypdf.annotations import Link
from pypdf.generic import ArrayObject, Fit, NameObject
from reportlab.lib.colors import black
from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas


ProgressCallback = Callable[[int, int, str], None]

PAGE_WIDTH, PAGE_HEIGHT = A4
A4_LANDSCAPE = landscape(A4)
FONT_NAME = "PDFMergeCJK"
BOLD_FONT_NAME = "PDFMergeCJKBold"
FALLBACK_FONT_NAME = "STSong-Light"
UNIFIED_FONT_SIZE = 12
PAGE_MARGIN = 54
TABLE_TOP = PAGE_HEIGHT - 112
TABLE_HEADER_HEIGHT = 30
TABLE_SERIAL_WIDTH = 48
TABLE_ROW_MIN_HEIGHT = 34
TABLE_LINE_HEIGHT = 18
TABLE_BOTTOM = 54


class PdfMergeError(Exception):
    """A user-facing PDF merge error."""


@dataclass(frozen=True)
class MergeDocument:
    path: Path
    title: str | None = None

    @property
    def display_title(self) -> str:
        return (self.title or self.path.stem).strip() or self.path.stem


@dataclass(frozen=True)
class MergeResult:
    output_path: Path
    document_count: int
    navigation_page_count: int
    total_page_count: int
    title_page_indices: tuple[int, ...]


@dataclass(frozen=True)
class _NavigationItem:
    document_index: int
    lines: tuple[str, ...]
    rect: tuple[float, float, float, float]


@dataclass(frozen=True)
class _PendingInternalLink:
    destination_container: object
    destination_key: str
    target_page_index: int
    destination_tail: tuple[object, ...]


def _font_name() -> str:
    if FONT_NAME in pdfmetrics.getRegisteredFontNames():
        return FONT_NAME
    candidates = (
        Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts" / "msyh.ttc",
        Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts" / "simhei.ttf",
    )
    for font_path in candidates:
        if not font_path.exists():
            continue
        try:
            pdfmetrics.registerFont(TTFont(FONT_NAME, str(font_path)))
            return FONT_NAME
        except Exception:
            continue
    if FALLBACK_FONT_NAME not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(UnicodeCIDFont(FALLBACK_FONT_NAME))
    return FALLBACK_FONT_NAME


def _bold_font_name(font_name: str) -> str:
    if BOLD_FONT_NAME in pdfmetrics.getRegisteredFontNames():
        return BOLD_FONT_NAME
    if font_name == FONT_NAME:
        candidates = (
            Path(os.environ.get("WINDIR", r"C:\Windows"))
            / "Fonts"
            / "msyhbd.ttc",
            Path(os.environ.get("WINDIR", r"C:\Windows"))
            / "Fonts"
            / "simhei.ttf",
        )
        for font_path in candidates:
            if not font_path.exists():
                continue
            try:
                pdfmetrics.registerFont(
                    TTFont(BOLD_FONT_NAME, str(font_path))
                )
                return BOLD_FONT_NAME
            except Exception:
                continue
    return font_name


def _ellipsize(text: str, font_name: str, size: float, width: float) -> str:
    if pdfmetrics.stringWidth(text, font_name, size) <= width:
        return text
    suffix = "…"
    result = text
    while result and pdfmetrics.stringWidth(
        result + suffix, font_name, size
    ) > width:
        result = result[:-1]
    return (result.rstrip() + suffix) if result else suffix


def _wrap_text(
    text: str,
    font_name: str,
    size: float,
    width: float,
    max_lines: int,
) -> tuple[str, ...]:
    remaining = text.strip()
    lines: list[str] = []
    while remaining and len(lines) < max_lines:
        if pdfmetrics.stringWidth(remaining, font_name, size) <= width:
            lines.append(remaining)
            remaining = ""
            break
        split_at = 1
        for index in range(1, len(remaining) + 1):
            if pdfmetrics.stringWidth(
                remaining[:index], font_name, size
            ) > width:
                break
            split_at = index
        candidate = remaining[:split_at]
        if " " in candidate and split_at < len(remaining):
            word_split = candidate.rfind(" ")
            if word_split > max(2, split_at // 2):
                split_at = word_split
        lines.append(remaining[:split_at].rstrip())
        remaining = remaining[split_at:].lstrip()
    if remaining and lines:
        lines[-1] = _ellipsize(
            lines[-1] + remaining, font_name, size, width
        )
    return tuple(lines or ["未命名文档"])


def _navigation_layout(
    documents: Sequence[MergeDocument],
    font_name: str,
) -> list[list[_NavigationItem]]:
    pages: list[list[_NavigationItem]] = [[]]
    y = TABLE_TOP - TABLE_HEADER_HEIGHT
    table_right = PAGE_WIDTH - PAGE_MARGIN
    title_x = PAGE_MARGIN + TABLE_SERIAL_WIDTH + 10
    title_width = table_right - title_x - 10
    for document_index, document in enumerate(documents):
        lines = _wrap_text(
            document.display_title,
            font_name,
            UNIFIED_FONT_SIZE,
            title_width,
            max_lines=2,
        )
        item_height = max(
            TABLE_ROW_MIN_HEIGHT,
            14 + TABLE_LINE_HEIGHT * len(lines),
        )
        if pages[-1] and y - item_height < TABLE_BOTTOM:
            pages.append([])
            y = TABLE_TOP - TABLE_HEADER_HEIGHT
        rect = (
            title_x - 2,
            y - item_height + 2,
            table_right - 4,
            y - 2,
        )
        pages[-1].append(
            _NavigationItem(document_index, lines, rect)
        )
        y -= item_height
    return pages


def _navigation_pdf(
    font_name: str,
    bold_font_name: str,
    layout: Sequence[Sequence[_NavigationItem]],
) -> BytesIO:
    stream = BytesIO()
    pdf = canvas.Canvas(stream, pagesize=A4, pageCompression=1)
    table_left = PAGE_MARGIN
    table_right = PAGE_WIDTH - PAGE_MARGIN
    serial_right = table_left + TABLE_SERIAL_WIDTH
    header_bottom = TABLE_TOP - TABLE_HEADER_HEIGHT
    for items in layout:
        pdf.setFillColor(black)
        table_bottom = items[-1].rect[1] - 2
        pdf.setStrokeColor(black)
        pdf.setLineWidth(0.5)
        pdf.rect(
            table_left,
            table_bottom,
            table_right - table_left,
            TABLE_TOP - table_bottom,
            stroke=1,
            fill=0,
        )
        pdf.line(serial_right, table_bottom, serial_right, TABLE_TOP)
        pdf.line(table_left, header_bottom, table_right, header_bottom)

        pdf.setFont(bold_font_name, UNIFIED_FONT_SIZE)
        serial_center = table_left + TABLE_SERIAL_WIDTH / 2
        pdf.drawCentredString(serial_center, TABLE_TOP - 20, "序号")
        pdf.drawString(serial_right + 10, TABLE_TOP - 20, "文件名称")

        for item in items:
            row_top = item.rect[3] + 2
            row_bottom = item.rect[1] - 2
            line_y = row_top - 20
            pdf.setFont(font_name, UNIFIED_FONT_SIZE)
            pdf.drawCentredString(
                serial_center,
                line_y,
                f"{item.document_index + 1:02d}",
            )
            for line in item.lines:
                pdf.drawString(serial_right + 10, line_y, line)
                line_y -= TABLE_LINE_HEIGHT
            pdf.line(table_left, row_bottom, table_right, row_bottom)
        pdf.showPage()
    pdf.save()
    stream.seek(0)
    return stream


def _title_pdf(
    title: str,
    font_name: str,
    bold_font_name: str,
) -> BytesIO:
    stream = BytesIO()
    pdf = canvas.Canvas(stream, pagesize=A4, pageCompression=1)
    pdf.setFillColor(black)
    pdf.setFont(bold_font_name, UNIFIED_FONT_SIZE)
    pdf.drawString(PAGE_MARGIN, PAGE_HEIGHT - 180, "文件名称：")
    lines = _wrap_text(
        title,
        font_name,
        UNIFIED_FONT_SIZE,
        PAGE_WIDTH - 2 * PAGE_MARGIN,
        max_lines=8,
    )
    line_y = PAGE_HEIGHT - 220
    pdf.setFont(font_name, UNIFIED_FONT_SIZE)
    for line in lines:
        pdf.drawString(PAGE_MARGIN, line_y, line)
        line_y -= TABLE_LINE_HEIGHT
    pdf.showPage()
    pdf.save()
    stream.seek(0)
    return stream


def inspect_pdf(path: Path) -> int:
    source = Path(path)
    if not source.exists() or not source.is_file():
        raise PdfMergeError(f"找不到 PDF：{source}")
    if source.suffix.lower() != ".pdf":
        raise PdfMergeError(f"不是 PDF 文件：{source.name}")
    try:
        reader = PdfReader(source)
        if reader.is_encrypted and not reader.decrypt(""):
            raise PdfMergeError(f"PDF 需要密码，无法合并：{source.name}")
        page_count = len(reader.pages)
    except PdfMergeError:
        raise
    except Exception as exc:
        raise PdfMergeError(f"无法读取 PDF：{source.name}") from exc
    if page_count < 1:
        raise PdfMergeError(f"PDF 没有页面：{source.name}")
    return page_count


def _transformed_bounds(
    page_box: object,
    transformation: Transformation,
) -> tuple[float, float, float, float]:
    corners = (
        (float(page_box.left), float(page_box.bottom)),
        (float(page_box.left), float(page_box.top)),
        (float(page_box.right), float(page_box.top)),
        (float(page_box.right), float(page_box.bottom)),
    )
    transformed = [
        transformation.apply_on(point) for point in corners
    ]
    return (
        min(point[0] for point in transformed),
        min(point[1] for point in transformed),
        max(point[0] for point in transformed),
        max(point[1] for point in transformed),
    )


def _a4_page_transform(
    page: PageObject,
) -> tuple[float, float, Transformation]:
    media_box = page.mediabox
    rotation = page.rotation
    transformation = Transformation()
    if rotation:
        transformation = (
            transformation.translate(
                -float(media_box.left + media_box.width / 2),
                -float(media_box.bottom + media_box.height / 2),
            )
            .rotate(-rotation)
        )
        media_bounds = _transformed_bounds(media_box, transformation)
        transformation = transformation.translate(
            -media_bounds[0],
            -media_bounds[1],
        )

    left, bottom, right, top = _transformed_bounds(
        page.cropbox,
        transformation,
    )
    source_width = right - left
    source_height = top - bottom
    if source_width <= 0 or source_height <= 0:
        raise PdfMergeError("PDF 页面尺寸无效，无法适配 A4。")
    target_width, target_height = (
        A4_LANDSCAPE
        if source_width > source_height
        else A4
    )
    scale = min(
        target_width / source_width,
        target_height / source_height,
    )
    translate_x = (
        (target_width - source_width * scale) / 2
        - left * scale
    )
    translate_y = (
        (target_height - source_height * scale) / 2
        - bottom * scale
    )
    return (
        target_width,
        target_height,
        transformation.scale(scale).translate(
            translate_x,
            translate_y,
        ),
    )


def _internal_link_details(
    reader: PdfReader,
    annotation: object,
) -> tuple[int, str, tuple[object, ...]] | None:
    annotation_object = annotation.get_object()
    destination_key = "/Dest"
    destination = annotation_object.get(destination_key)
    if destination is None:
        action = annotation_object.get("/A")
        if action is None:
            return None
        action_object = action.get_object()
        if action_object.get("/S") != "/GoTo":
            return None
        destination_key = "/D"
        destination = action_object.get(destination_key)
    destination = destination.get_object()
    if not isinstance(destination, ArrayObject) or not destination:
        return None
    target = destination[0]
    for page_index, page in enumerate(reader.pages):
        if page.indirect_reference == target:
            return (
                page_index,
                destination_key,
                tuple(destination[1:]),
            )
    return None


def _append_a4_document(
    writer: PdfWriter,
    document: MergeDocument,
    first_output_page: int,
) -> int:
    reader = PdfReader(document.path)
    if reader.is_encrypted and not reader.decrypt(""):
        raise PdfMergeError(
            f"PDF 需要密码，无法合并：{document.path.name}"
        )
    pending_links: list[_PendingInternalLink] = []
    for source_page in reader.pages:
        target_width, target_height, transformation = (
            _a4_page_transform(source_page)
        )
        output_page = writer.add_blank_page(
            width=target_width,
            height=target_height,
        )
        source_annotations = list(source_page.get("/Annots", []))
        output_page.merge_transformed_page(
            source_page,
            transformation,
        )
        if not source_annotations:
            continue
        output_annotations = list(output_page.get("/Annots", []))
        for source_annotation, output_annotation in zip(
            source_annotations,
            output_annotations[-len(source_annotations) :],
        ):
            details = _internal_link_details(
                reader,
                source_annotation,
            )
            if details is None:
                continue
            target_page_index, destination_key, destination_tail = (
                details
            )
            output_annotation_object = output_annotation.get_object()
            destination_container = output_annotation_object
            if destination_key == "/D":
                destination_container = output_annotation_object[
                    "/A"
                ].get_object()
            pending_links.append(
                _PendingInternalLink(
                    destination_container,
                    destination_key,
                    target_page_index,
                    destination_tail,
                )
            )

    for pending in pending_links:
        target_page = writer.pages[
            first_output_page + pending.target_page_index
        ].indirect_reference
        if target_page is None:
            raise PdfMergeError("无法保留源 PDF 内部链接。")
        pending.destination_container[
            NameObject(pending.destination_key)
        ] = ArrayObject([target_page, *pending.destination_tail])
    return len(reader.pages)


def merge_pdfs(
    documents: Sequence[MergeDocument],
    output_path: Path,
    progress: ProgressCallback | None = None,
) -> MergeResult:
    if not documents:
        raise PdfMergeError("请至少添加一份 PDF。")

    output = Path(output_path)
    if output.suffix.lower() != ".pdf":
        raise PdfMergeError("输出文件必须使用 .pdf 扩展名。")
    output.parent.mkdir(parents=True, exist_ok=True)
    output_resolved = output.resolve()

    page_counts: list[int] = []
    normalized_documents: list[MergeDocument] = []
    seen: set[Path] = set()
    for document in documents:
        source = Path(document.path).resolve()
        if source == output_resolved:
            raise PdfMergeError("输出文件不能与任一源 PDF 相同。")
        if source in seen:
            raise PdfMergeError(f"列表中存在重复 PDF：{source.name}")
        seen.add(source)
        page_counts.append(inspect_pdf(source))
        normalized_documents.append(MergeDocument(source, document.title))

    font_name = _font_name()
    bold_font_name = _bold_font_name(font_name)
    navigation_layout = _navigation_layout(normalized_documents, font_name)
    writer = PdfWriter()
    navigation_stream = _navigation_pdf(
        font_name,
        bold_font_name,
        navigation_layout,
    )
    writer.append(PdfReader(navigation_stream), import_outline=False)

    title_page_indices: list[int] = []
    current_page = len(navigation_layout)
    total_documents = len(normalized_documents)
    for index, (document, page_count) in enumerate(
        zip(normalized_documents, page_counts), start=1
    ):
        title_page_indices.append(current_page)
        title_stream = _title_pdf(
            document.display_title,
            font_name,
            bold_font_name,
        )
        writer.append(PdfReader(title_stream), import_outline=False)
        source_page_count = _append_a4_document(
            writer,
            document,
            current_page + 1,
        )
        if source_page_count != page_count:
            raise PdfMergeError(
                f"PDF 页数在合并期间发生变化：{document.path.name}"
            )
        current_page += 1 + page_count
        if progress:
            progress(index, total_documents, document.display_title)

    for navigation_page_index, page_items in enumerate(navigation_layout):
        for item in page_items:
            target_page = writer.pages[
                title_page_indices[item.document_index]
            ].indirect_reference
            if target_page is None:
                raise PdfMergeError("无法建立导航链接：目标页无有效引用。")
            annotation = writer.add_annotation(
                page_number=navigation_page_index,
                annotation=Link(
                    rect=item.rect,
                    target_page_index=title_page_indices[
                        item.document_index
                    ],
                    fit=Fit.fit(),
                ),
            )
            annotation[NameObject("/Dest")] = ArrayObject(
                [target_page, NameObject("/Fit")]
            )

    temporary = output.with_name(
        f".{output.stem}.{uuid4().hex}.part.pdf"
    )
    try:
        with temporary.open("wb") as stream:
            writer.write(stream)
        os.replace(temporary, output)
    except Exception as exc:
        temporary.unlink(missing_ok=True)
        raise PdfMergeError(f"无法写入输出 PDF：{output}") from exc
    finally:
        writer.close()
        navigation_stream.close()

    return MergeResult(
        output_path=output,
        document_count=total_documents,
        navigation_page_count=len(navigation_layout),
        total_page_count=current_page,
        title_page_indices=tuple(title_page_indices),
    )
