from __future__ import annotations

from datetime import date
from pathlib import Path
from types import SimpleNamespace
from tkinter import Tk

import pytest
from PIL import Image
from reportlab.pdfgen import canvas

import pdf_merge_tool.app as app_module
from pdf_merge_tool.app import PdfMergeApp
from pdf_merge_tool.core import MergeResult


def _make_pdf(path: Path, pages: int = 1) -> None:
    pdf = canvas.Canvas(str(path), pagesize=(200, 300))
    for page_number in range(pages):
        pdf.drawString(20, 150, f"page {page_number + 1}")
        pdf.showPage()
    pdf.save()


@pytest.fixture(scope="module")
def tk_root() -> Tk:
    root = Tk()
    root.attributes("-alpha", 0.0)
    root.geometry("1080x720+20+20")
    yield root
    root.destroy()


def _build_app(root: Tk) -> PdfMergeApp:
    for child in root.winfo_children():
        child.destroy()
    app = PdfMergeApp(root)
    root.update()
    return app


def test_icon_assets_include_transparency_and_windows_sizes() -> None:
    assets = Path(__file__).resolve().parents[1] / "assets"
    png_path = assets / "app-icon.png"
    ico_path = assets / "app-icon.ico"

    with Image.open(png_path) as png:
        assert png.mode == "RGBA"
        assert png.size == (512, 512)
        alpha = png.getchannel("A")
        assert alpha.getpixel((0, 0)) == 0
        assert alpha.getpixel((256, 256)) == 255
    with Image.open(ico_path) as icon:
        assert {
            (16, 16),
            (24, 24),
            (32, 32),
            (48, 48),
            (64, 64),
            (128, 128),
            (256, 256),
        }.issubset(icon.ico.sizes())


def test_window_uses_independent_app_icon(
    monkeypatch: pytest.MonkeyPatch,
    tk_root: Tk,
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        tk_root,
        "iconbitmap",
        lambda *, default: calls.append(default),
    )

    app = _build_app(tk_root)

    assert app.window_icon_path.name == "app-icon.ico"
    assert app.window_icon_path.is_file()
    assert calls == [str(app.window_icon_path)]


def test_windows_dpi_uses_system_awareness(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[int] = []

    class FakeShcore:
        @staticmethod
        def SetProcessDpiAwareness(value: int) -> None:
            calls.append(value)

    class FakeUser32:
        @staticmethod
        def SetProcessDpiAwarenessContext(_value: object) -> None:
            raise AssertionError("Per-Monitor V2 must not be requested")

        @staticmethod
        def SetProcessDPIAware() -> None:
            raise AssertionError("legacy fallback should not be needed")

    monkeypatch.setattr(app_module.os, "name", "nt")
    monkeypatch.setattr(
        app_module.ctypes,
        "windll",
        SimpleNamespace(shcore=FakeShcore(), user32=FakeUser32()),
    )

    app_module.enable_high_dpi()

    assert calls == [1]


def test_external_drop_adds_pdfs_and_ignores_other_items(
    tmp_path: Path,
    tk_root: Tk,
) -> None:
    first = tmp_path / "first.pdf"
    dropped = tmp_path / "dropped file.pdf"
    ignored = tmp_path / "说明.txt"
    _make_pdf(first)
    _make_pdf(dropped)
    ignored.write_text("not a PDF", encoding="utf-8")
    app = _build_app(tk_root)
    assert app.drag_drop_enabled
    app.add_paths([first])
    drop_data = tk_root.tk.call(
        "list",
        str(first),
        str(dropped),
        str(ignored),
    )

    result = app._on_pdf_drop(SimpleNamespace(data=drop_data))

    assert result == app_module.COPY
    assert [item.path for item in app.documents] == [
        first.resolve(),
        dropped.resolve(),
    ]
    assert "忽略 1 份重复文件" in app.status_var.get()
    assert "已忽略 1 个非 PDF 项目" in app.status_var.get()


def test_list_numbers_and_keyboard_selection_do_not_reorder(
    tmp_path: Path,
    tk_root: Tk,
) -> None:
    paths = [tmp_path / f"{name}.pdf" for name in ("甲", "乙", "丙")]
    for path in paths:
        _make_pdf(path)
    app = _build_app(tk_root)
    app.add_paths(paths)
    original = [document.uid for document in app.documents]
    assert [
        app.document_tree.item(uid, "values")[0] for uid in original
    ] == ["1", "2", "3"]
    app._select_index(1)

    assert app._select_next(None) == "break"
    assert app._selected_index() == 2
    assert [document.uid for document in app.documents] == original
    assert app._select_previous(None) == "break"
    assert app._selected_index() == 1
    assert [document.uid for document in app.documents] == original
    assert app.document_tree.bind("<Alt-Up>")
    assert app.document_tree.bind("<Alt-Down>")


def test_alt_move_buttons_and_drag_keep_moved_document_selected(
    tmp_path: Path,
    tk_root: Tk,
) -> None:
    paths = [tmp_path / f"{name}.pdf" for name in ("a", "b", "c", "d")]
    for path in paths:
        _make_pdf(path)
    app = _build_app(tk_root)
    app.add_paths(paths)
    app._select_index(2)
    selected_uid = app.documents[2].uid

    assert app._move_up_shortcut(None) == "break"
    assert [item.path.stem for item in app.documents] == [
        "a",
        "c",
        "b",
        "d",
    ]
    assert app.documents[app._selected_index()].uid == selected_uid

    app.move_selected_top()
    assert app.documents[0].uid == selected_uid
    assert app._selected_index() == 0
    app.move_selected_bottom()
    assert app.documents[-1].uid == selected_uid
    assert app._selected_index() == 3

    source_uid = app.documents[2].uid
    target_uid = app.documents[0].uid
    source_box = app.document_tree.bbox(source_uid)
    target_box = app.document_tree.bbox(target_uid)
    assert source_box and target_box
    app._drag_start(SimpleNamespace(y=source_box[1] + 4))
    app._drag_release(SimpleNamespace(y=target_box[1] + 4))
    assert app.documents[0].uid == source_uid
    assert app._selected_index() == 0


def test_ctrl_shift_click_and_ctrl_a_select_multiple_documents(
    tmp_path: Path,
    tk_root: Tk,
) -> None:
    paths = [tmp_path / f"{name}.pdf" for name in ("a", "b", "c", "d", "e")]
    for path in paths:
        _make_pdf(path)
    app = _build_app(tk_root)
    app.add_paths(paths)
    uids = [document.uid for document in app.documents]
    assert str(app.document_tree.cget("selectmode")) == "extended"

    second_box = app.document_tree.bbox(uids[1])
    fourth_box = app.document_tree.bbox(uids[3])
    fifth_box = app.document_tree.bbox(uids[4])
    assert second_box and fourth_box and fifth_box
    app._drag_start(
        SimpleNamespace(x=8, y=second_box[1] + 4, state=0)
    )
    app._drag_release(
        SimpleNamespace(x=8, y=second_box[1] + 4, state=0)
    )
    app._drag_start(
        SimpleNamespace(
            x=8,
            y=fourth_box[1] + 4,
            state=app_module.SHIFT_MASK,
        )
    )
    assert app._selected_uids() == tuple(uids[1:4])
    app._drag_start(
        SimpleNamespace(
            x=8,
            y=fifth_box[1] + 4,
            state=app_module.CONTROL_MASK,
        )
    )
    assert app._selected_uids() == tuple(uids[1:5])

    assert app._select_all(None) == "break"
    assert app._selected_uids() == tuple(uids)


def test_marquee_selects_intersecting_rows(
    tmp_path: Path,
    tk_root: Tk,
) -> None:
    paths = [tmp_path / f"{name}.pdf" for name in ("a", "b", "c", "d")]
    for path in paths:
        _make_pdf(path)
    app = _build_app(tk_root)
    app.add_paths(paths)
    uids = [document.uid for document in app.documents]
    second_box = app.document_tree.bbox(uids[1])
    last_box = app.document_tree.bbox(uids[-1])
    assert second_box and last_box
    blank_y = last_box[1] + last_box[3] + 8
    assert not app.document_tree.identify_row(blank_y)

    app._drag_start(SimpleNamespace(x=20, y=blank_y, state=0))
    app._drag_motion(
        SimpleNamespace(x=280, y=second_box[1] + 2, state=0)
    )

    assert app._selected_uids() == tuple(uids[1:])
    assert all(edge.winfo_manager() == "place" for edge in app.marquee_edges)
    app._drag_release(
        SimpleNamespace(x=280, y=second_box[1] + 2, state=0)
    )
    assert all(not edge.winfo_manager() for edge in app.marquee_edges)


def test_heading_separator_drag_resizes_column_without_custom_drag(
    tk_root: Tk,
) -> None:
    app = _build_app(tk_root)
    tree = app.document_tree
    separator = next(
        (x, y)
        for y in range(1, 60)
        for x in range(1, tree.winfo_width())
        if tree.identify_region(x, y) == "separator"
    )
    separator_x, separator_y = separator
    original_width = int(tree.column("order", "width"))

    tree.event_generate(
        "<ButtonPress-1>",
        x=separator_x,
        y=separator_y,
    )
    tk_root.update()
    assert app.marquee_start is None
    assert app.drag_uid is None

    tree.event_generate(
        "<B1-Motion>",
        x=separator_x + 40,
        y=separator_y,
    )
    tk_root.update()
    tree.event_generate(
        "<ButtonRelease-1>",
        x=separator_x + 40,
        y=separator_y,
    )
    tk_root.update()

    assert int(tree.column("order", "width")) >= original_width + 35
    assert all(not edge.winfo_manager() for edge in app.marquee_edges)
    assert not app.drag_indicator.winfo_manager()


def test_batch_move_remove_and_drag_insertion_indicator(
    tmp_path: Path,
    tk_root: Tk,
) -> None:
    paths = [tmp_path / f"{name}.pdf" for name in ("a", "b", "c", "d", "e")]
    for path in paths:
        _make_pdf(path)
    app = _build_app(tk_root)
    app.add_paths(paths)
    uids = [document.uid for document in app.documents]
    app.document_tree.selection_set((uids[1], uids[3]))
    app.document_tree.focus(uids[3])

    app.move_selected_top()
    assert [item.path.stem for item in app.documents] == [
        "b",
        "d",
        "a",
        "c",
        "e",
    ]
    assert set(app._selected_uids()) == {uids[1], uids[3]}
    app.move_selected_by(1)
    assert [item.path.stem for item in app.documents] == [
        "a",
        "b",
        "d",
        "c",
        "e",
    ]
    app.remove_selected()
    assert [item.path.stem for item in app.documents] == ["a", "c", "e"]

    source_uid = app.documents[2].uid
    target_uid = app.documents[1].uid
    source_box = app.document_tree.bbox(source_uid)
    target_box = app.document_tree.bbox(target_uid)
    assert source_box and target_box
    event_y = target_box[1] + 1
    app._drag_start(
        SimpleNamespace(x=8, y=source_box[1] + 4, state=0)
    )
    app._drag_motion(SimpleNamespace(x=8, y=event_y, state=0))
    assert app.drag_indicator.winfo_manager() == "place"
    app._drag_release(SimpleNamespace(x=8, y=event_y, state=0))
    assert not app.drag_indicator.winfo_manager()
    assert [item.path.stem for item in app.documents] == ["a", "e", "c"]


def test_folder_load_uses_natural_filename_order(
    tmp_path: Path,
    monkeypatch,
    tk_root: Tk,
) -> None:
    _make_pdf(tmp_path / "文档10.pdf")
    _make_pdf(tmp_path / "文档2.pdf")
    (tmp_path / "说明.txt").write_text("not a pdf", encoding="utf-8")
    app = _build_app(tk_root)
    monkeypatch.setattr(
        app_module.filedialog,
        "askdirectory",
        lambda **_kwargs: str(tmp_path),
    )
    app.choose_folder()

    assert [item.path.name for item in app.documents] == [
        "文档2.pdf",
        "文档10.pdf",
    ]


def test_start_merge_runs_from_current_interface_order(
    tmp_path: Path,
    monkeypatch,
    tk_root: Tk,
) -> None:
    first = tmp_path / "first.pdf"
    second = tmp_path / "second.pdf"
    desktop = tmp_path / "Desktop"
    output = desktop / "PDF 合并输出_2026-07-28-02.pdf"
    _make_pdf(first)
    _make_pdf(second)
    calls: list[tuple[list[Path], Path]] = []
    notices: list[str] = []

    class ImmediateThread:
        def __init__(self, *, target, daemon: bool) -> None:
            self.target = target
            assert daemon is True

        def start(self) -> None:
            self.target()

    def fake_merge(documents, output_path, progress):
        calls.append(([item.path for item in documents], output_path))
        progress(1, 2, "second")
        progress(2, 2, "first")
        return MergeResult(output_path, 2, 1, 5, (1, 3))

    app = _build_app(tk_root)
    app.add_paths([first, second])
    app._select_index(1)
    app.move_selected_top()
    desktop.mkdir()
    (desktop / "PDF 合并输出_2026-07-28-01.pdf").write_bytes(
        b"existing"
    )
    monkeypatch.setattr(app, "_desktop_directory", lambda: desktop)
    monkeypatch.setattr(
        app,
        "_reserve_desktop_output_path",
        lambda _desktop: output,
    )
    monkeypatch.setattr(
        app_module.filedialog,
        "asksaveasfilename",
        lambda **_kwargs: pytest.fail("不应再打开保存位置对话框"),
    )
    monkeypatch.setattr(app_module, "merge_pdfs", fake_merge)
    monkeypatch.setattr(app_module.threading, "Thread", ImmediateThread)
    monkeypatch.setattr(
        app_module.messagebox,
        "showinfo",
        lambda _title, message, **_kwargs: notices.append(message),
    )

    app.start_merge()
    tk_root.update()

    assert calls == [([second, first], output)]
    assert app.busy is False
    assert "合并完成" in app.status_var.get()
    assert notices and str(output) in notices[0]


def test_desktop_output_name_increments_without_overwriting(
    tmp_path: Path,
) -> None:
    desktop = tmp_path / "Desktop"
    first = PdfMergeApp._reserve_desktop_output_path(
        desktop,
        date(2026, 7, 28),
    )
    first.write_bytes(b"first result")
    second = PdfMergeApp._reserve_desktop_output_path(
        desktop,
        date(2026, 7, 28),
    )

    assert first.name == "PDF 合并输出_2026-07-28-01.pdf"
    assert second.name == "PDF 合并输出_2026-07-28-02.pdf"
    assert first.read_bytes() == b"first result"
    assert second.read_bytes() == b""


def test_main_controls_remain_visible_at_150_and_200_percent(
    tk_root: Tk,
) -> None:
    original_scaling = float(tk_root.tk.call("tk", "scaling"))
    try:
        for scaling in (2.0, 2.6667):
            tk_root.tk.call("tk", "scaling", scaling)
            app = _build_app(tk_root)
            tk_root.update_idletasks()
            root_left = tk_root.winfo_rootx()
            root_top = tk_root.winfo_rooty()
            root_right = root_left + tk_root.winfo_width()
            root_bottom = root_top + tk_root.winfo_height()
            assert app.document_tree.winfo_height() >= 180
            assert (
                app.count_label.winfo_width()
                >= app.count_label.winfo_reqwidth()
            )
            assert (
                app.move_hint_label.winfo_width()
                >= app.move_hint_label.winfo_reqwidth()
            )
            assert app.merge_button.winfo_rootx() >= root_left
            assert (
                app.merge_button.winfo_rootx()
                + app.merge_button.winfo_width()
                <= root_right
            )
            assert app.merge_button.winfo_rooty() >= root_top
            assert (
                app.merge_button.winfo_rooty()
                + app.merge_button.winfo_height()
                <= root_bottom
            )
    finally:
        tk_root.tk.call("tk", "scaling", original_scaling)
