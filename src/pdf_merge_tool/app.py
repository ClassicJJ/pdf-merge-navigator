from __future__ import annotations

import ctypes
import os
import re
import sys
import threading
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from tkinter import (
    BOTH,
    END,
    Frame as TkFrame,
    LEFT,
    RIGHT,
    StringVar,
    TclError,
    Tk,
    filedialog,
    messagebox,
)
from tkinter import ttk

from tkinterdnd2 import COPY, DND_FILES, TkinterDnD

from .core import MergeDocument, PdfMergeError, inspect_pdf, merge_pdfs
from .ordering import (
    move_item_to_insertion,
    move_selected_by as move_documents_by,
    move_selected_to_edge,
)


BG = "#F3F5F8"
SURFACE = "#FFFFFF"
SURFACE_MUTED = "#F8FAFC"
TEXT = "#172033"
TEXT_MUTED = "#667085"
PRIMARY = "#246BFD"
PRIMARY_HOVER = "#1559DA"
BORDER = "#D9DEE8"
DANGER = "#C83B4A"
SHIFT_MASK = 0x0001
CONTROL_MASK = 0x0004


def _resource_path(relative_path: str) -> Path:
    bundle_root = Path(
        getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2])
    )
    return bundle_root / relative_path


@dataclass(frozen=True)
class ListedDocument:
    uid: str
    path: Path
    page_count: int


def enable_high_dpi() -> None:
    if os.name != "nt":
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
        return
    except (AttributeError, OSError):
        pass
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except (AttributeError, OSError):
        pass


def _natural_key(path: Path) -> list[object]:
    return [
        int(part) if part.isdigit() else part.casefold()
        for part in re.split(r"(\d+)", path.name)
    ]


class PdfMergeApp:
    def __init__(self, root: Tk) -> None:
        self.root = root
        self.root.title("PDF Merge Navigator")
        self.window_icon_path = _resource_path("assets/app-icon.ico")
        if self.window_icon_path.is_file():
            try:
                self.root.iconbitmap(default=str(self.window_icon_path))
            except TclError:
                pass
        self.root.geometry("1080x720")
        self.root.minsize(900, 620)
        self.root.configure(bg=BG)
        self.root.protocol("WM_DELETE_WINDOW", self.close)

        self.documents: list[ListedDocument] = []
        self.next_uid = 1
        self.drag_uid: str | None = None
        self.drag_insert_index: int | None = None
        self.selection_anchor_uid: str | None = None
        self.marquee_start: tuple[int, int] | None = None
        self.marquee_original_selection: tuple[str, ...] = ()
        self.drag_drop_enabled = False
        self.busy = False
        self.status_var = StringVar(
            value="请添加或拖入 PDF，所有处理都在本机完成"
        )
        self.count_var = StringVar(value="尚未添加 PDF")

        self._configure_style()
        self._build_ui()
        self._enable_file_drop()
        self._bind_shortcuts()
        self._refresh_controls()

    def _configure_style(self) -> None:
        style = ttk.Style()
        style.theme_use("clam")
        style.configure(".", font=("Microsoft YaHei UI", 10))
        style.configure("TFrame", background=BG)
        style.configure("Card.TFrame", background=SURFACE)
        style.configure(
            "TLabel",
            background=BG,
            foreground=TEXT,
        )
        style.configure(
            "Card.TLabel",
            background=SURFACE,
            foreground=TEXT,
        )
        style.configure(
            "Muted.TLabel",
            background=BG,
            foreground=TEXT_MUTED,
        )
        style.configure(
            "CardMuted.TLabel",
            background=SURFACE,
            foreground=TEXT_MUTED,
        )
        style.configure(
            "Header.TLabel",
            background=BG,
            foreground=TEXT,
            font=("Microsoft YaHei UI", 20, "bold"),
        )
        style.configure(
            "Primary.TButton",
            background=PRIMARY,
            foreground="#FFFFFF",
            padding=(18, 10),
            borderwidth=0,
            focusthickness=0,
        )
        style.map(
            "Primary.TButton",
            background=[
                ("disabled", "#AFC3F5"),
                ("active", PRIMARY_HOVER),
            ],
        )
        style.configure(
            "Secondary.TButton",
            background=SURFACE_MUTED,
            foreground=TEXT,
            padding=(12, 8),
            bordercolor=BORDER,
            borderwidth=1,
        )
        style.map(
            "Secondary.TButton",
            background=[("active", "#EAF0FA")],
        )
        style.configure(
            "Treeview",
            background=SURFACE,
            fieldbackground=SURFACE,
            foreground=TEXT,
            rowheight=34,
            borderwidth=0,
        )
        style.configure(
            "Treeview.Heading",
            background=SURFACE_MUTED,
            foreground=TEXT_MUTED,
            font=("Microsoft YaHei UI", 9, "bold"),
            padding=(8, 8),
            bordercolor=BORDER,
        )
        style.map(
            "Treeview",
            background=[("selected", "#DCE7FF")],
            foreground=[("selected", TEXT)],
        )

    def _build_ui(self) -> None:
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(1, weight=1)

        header = ttk.Frame(self.root, padding=(28, 22, 28, 16))
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)
        ttk.Label(
            header,
            text="PDF Merge Navigator",
            style="Header.TLabel",
        ).grid(row=0, column=0, sticky="w")
        ttk.Label(
            header,
            text="按列表顺序生成可点击文件清单和文件名称页",
            style="Muted.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(4, 0))
        ttk.Label(
            header,
            text="本地处理 · 原文件不修改",
            style="Muted.TLabel",
        ).grid(row=0, column=1, rowspan=2, sticky="e")

        card = ttk.Frame(
            self.root,
            style="Card.TFrame",
            padding=(20, 18, 20, 16),
        )
        card.grid(row=1, column=0, sticky="nsew", padx=28, pady=(0, 18))
        card.columnconfigure(0, weight=1)
        card.rowconfigure(2, weight=1)

        toolbar = ttk.Frame(card, style="Card.TFrame")
        toolbar.grid(row=0, column=0, sticky="ew")
        self.add_files_button = ttk.Button(
            toolbar,
            text="添加 PDF",
            style="Secondary.TButton",
            command=self.choose_files,
        )
        self.add_files_button.grid(row=0, column=0, padx=(0, 8))
        self.add_folder_button = ttk.Button(
            toolbar,
            text="添加文件夹",
            style="Secondary.TButton",
            command=self.choose_folder,
        )
        self.add_folder_button.grid(row=0, column=1, padx=(0, 8))
        self.remove_button = ttk.Button(
            toolbar,
            text="移除所选",
            style="Secondary.TButton",
            command=self.remove_selected,
        )
        self.remove_button.grid(row=0, column=2, padx=(0, 8))
        self.clear_button = ttk.Button(
            toolbar,
            text="清空列表",
            style="Secondary.TButton",
            command=self.clear_documents,
        )
        self.clear_button.grid(row=0, column=3)
        info_bar = ttk.Frame(card, style="Card.TFrame")
        info_bar.grid(row=1, column=0, sticky="ew", pady=(14, 8))
        info_bar.columnconfigure(0, weight=1)
        ttk.Label(
            info_bar,
            text="可从资源管理器拖入 PDF；最终按下方顺序合并",
            style="CardMuted.TLabel",
        ).grid(row=0, column=0, sticky="w")
        self.count_label = ttk.Label(
            info_bar,
            textvariable=self.count_var,
            style="CardMuted.TLabel",
        )
        self.count_label.grid(row=0, column=1, sticky="e", padx=(16, 0))

        tree_frame = ttk.Frame(card, style="Card.TFrame")
        tree_frame.grid(row=2, column=0, sticky="nsew")
        tree_frame.columnconfigure(0, weight=1)
        tree_frame.rowconfigure(0, weight=1)
        self.document_tree = ttk.Treeview(
            tree_frame,
            columns=("order", "name", "pages", "path"),
            show="headings",
            selectmode="extended",
        )
        self.document_tree.heading("order", text="顺序")
        self.document_tree.heading("name", text="文档名称")
        self.document_tree.heading("pages", text="页数")
        self.document_tree.heading("path", text="位置")
        self.document_tree.column("order", width=64, minwidth=58, anchor="center")
        self.document_tree.column("name", width=270, minwidth=180)
        self.document_tree.column("pages", width=70, minwidth=64, anchor="center")
        self.document_tree.column("path", width=520, minwidth=260)
        scrollbar = ttk.Scrollbar(
            tree_frame,
            orient="vertical",
            command=self.document_tree.yview,
        )
        self.document_tree.configure(yscrollcommand=scrollbar.set)
        self.document_tree.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.drag_indicator = TkFrame(
            self.document_tree,
            background=PRIMARY,
            height=2,
        )
        self.marquee_edges = tuple(
            TkFrame(self.document_tree, background=PRIMARY)
            for _ in range(4)
        )

        move_bar = ttk.Frame(card, style="Card.TFrame")
        move_bar.grid(row=3, column=0, sticky="ew", pady=(12, 0))
        self.move_top_button = ttk.Button(
            move_bar,
            text="移到顶部",
            style="Secondary.TButton",
            command=self.move_selected_top,
        )
        self.move_up_button = ttk.Button(
            move_bar,
            text="上移",
            style="Secondary.TButton",
            command=lambda: self.move_selected_by(-1),
        )
        self.move_down_button = ttk.Button(
            move_bar,
            text="下移",
            style="Secondary.TButton",
            command=lambda: self.move_selected_by(1),
        )
        self.move_bottom_button = ttk.Button(
            move_bar,
            text="移到底部",
            style="Secondary.TButton",
            command=self.move_selected_bottom,
        )
        for column, button in enumerate(
            (
                self.move_top_button,
                self.move_up_button,
                self.move_down_button,
                self.move_bottom_button,
            )
        ):
            button.grid(row=0, column=column, padx=(0, 8))
        self.move_hint_label = ttk.Label(
            move_bar,
            text="支持多选和画框选择；拖动排序时横线表示插入位置",
            style="CardMuted.TLabel",
        )
        self.move_hint_label.grid(
            row=1,
            column=0,
            columnspan=4,
            sticky="w",
            pady=(9, 0),
        )

        footer = ttk.Frame(self.root, padding=(28, 0, 28, 24))
        footer.grid(row=2, column=0, sticky="ew")
        footer.columnconfigure(0, weight=1)
        ttk.Label(
            footer,
            textvariable=self.status_var,
            style="Muted.TLabel",
        ).grid(row=0, column=0, sticky="w")
        self.merge_button = ttk.Button(
            footer,
            text="开始合并",
            style="Primary.TButton",
            command=self.start_merge,
        )
        self.merge_button.grid(row=0, column=1, sticky="e")

        self._controls = (
            self.add_files_button,
            self.add_folder_button,
            self.remove_button,
            self.clear_button,
            self.move_top_button,
            self.move_up_button,
            self.move_down_button,
            self.move_bottom_button,
            self.merge_button,
        )

    def _bind_shortcuts(self) -> None:
        self.document_tree.bind("<<TreeviewSelect>>", self._selection_changed)
        self.document_tree.bind("<Up>", self._select_previous)
        self.document_tree.bind("<Down>", self._select_next)
        self.document_tree.bind("<Alt-Up>", self._move_up_shortcut)
        self.document_tree.bind("<Alt-Down>", self._move_down_shortcut)
        self.document_tree.bind("<Control-a>", self._select_all)
        self.document_tree.bind("<Control-A>", self._select_all)
        self.document_tree.bind("<Delete>", self._delete_shortcut)
        self.document_tree.bind("<ButtonPress-1>", self._drag_start)
        self.document_tree.bind("<B1-Motion>", self._drag_motion)
        self.document_tree.bind("<ButtonRelease-1>", self._drag_release)

    def _enable_file_drop(self) -> None:
        try:
            TkinterDnD.require(self.root)
            self.document_tree.drop_target_register(DND_FILES)
            self.document_tree.dnd_bind("<<Drop>>", self._on_pdf_drop)
        except Exception:
            self.drag_drop_enabled = False
            return
        self.drag_drop_enabled = True

    def _on_pdf_drop(self, event: object) -> str:
        if self.busy:
            self.status_var.set("正在合并，暂时不能添加文件")
            return COPY
        try:
            raw_paths = self.root.tk.splitlist(getattr(event, "data", ""))
        except Exception:
            raw_paths = ()
        pdf_paths: list[Path] = []
        ignored = 0
        for raw_path in raw_paths:
            path = Path(raw_path)
            if path.is_file() and path.suffix.lower() == ".pdf":
                pdf_paths.append(path)
            else:
                ignored += 1
        if not pdf_paths:
            self.status_var.set("拖入内容中没有可添加的 PDF 文件")
            return COPY
        self.add_paths(pdf_paths)
        if ignored:
            status = self.status_var.get()
            self.status_var.set(
                f"{status}；已忽略 {ignored} 个非 PDF 项目"
            )
        return COPY

    def choose_files(self) -> None:
        paths = filedialog.askopenfilenames(
            parent=self.root,
            title="选择要合并的 PDF",
            filetypes=[("PDF 文件", "*.pdf")],
        )
        if paths:
            self.add_paths([Path(path) for path in paths])

    def choose_folder(self) -> None:
        selected = filedialog.askdirectory(
            parent=self.root,
            title="选择包含 PDF 的文件夹",
        )
        if not selected:
            return
        folder = Path(selected)
        paths = sorted(
            (
                path
                for path in folder.iterdir()
                if path.is_file() and path.suffix.lower() == ".pdf"
            ),
            key=_natural_key,
        )
        if not paths:
            self.status_var.set("所选文件夹第一层没有 PDF")
            messagebox.showinfo(
                "没有找到 PDF",
                "所选文件夹第一层没有可载入的 PDF 文件。",
                parent=self.root,
            )
            return
        self.add_paths(paths)

    def add_paths(self, paths: list[Path]) -> None:
        existing = {
            os.path.normcase(str(document.path.resolve()))
            for document in self.documents
        }
        added: list[ListedDocument] = []
        duplicates = 0
        failures: list[str] = []
        for raw_path in paths:
            path = Path(raw_path).resolve()
            key = os.path.normcase(str(path))
            if key in existing:
                duplicates += 1
                continue
            try:
                page_count = inspect_pdf(path)
            except PdfMergeError as exc:
                failures.append(str(exc))
                continue
            document = ListedDocument(
                uid=f"document:{self.next_uid}",
                path=path,
                page_count=page_count,
            )
            self.next_uid += 1
            self.documents.append(document)
            added.append(document)
            existing.add(key)
        selected_uid = added[-1].uid if added else None
        self._refresh_tree(selected_uid)
        parts = []
        if added:
            parts.append(f"已添加 {len(added)} 份 PDF")
        if duplicates:
            parts.append(f"忽略 {duplicates} 份重复文件")
        if failures:
            parts.append(f"{len(failures)} 份无法读取")
            messagebox.showwarning(
                "部分 PDF 未添加",
                "\n".join(failures[:8]),
                parent=self.root,
            )
        self.status_var.set("；".join(parts) or "没有添加新 PDF")

    def _refresh_tree(
        self,
        selected_uids: str | tuple[str, ...] | None = None,
        focus_uid: str | None = None,
    ) -> None:
        if selected_uids is None:
            selected = self._selected_uids()
            focus = focus_uid or self.document_tree.focus()
        else:
            selected = (
                (selected_uids,)
                if isinstance(selected_uids, str)
                else selected_uids
            )
            focus = focus_uid or (selected[0] if selected else "")
        self.document_tree.delete(*self.document_tree.get_children())
        for index, document in enumerate(self.documents, start=1):
            self.document_tree.insert(
                "",
                END,
                iid=document.uid,
                values=(
                    index,
                    document.path.name,
                    document.page_count,
                    str(document.path.parent),
                ),
            )
        valid_selection = tuple(
            uid for uid in selected if self.document_tree.exists(uid)
        )
        if valid_selection:
            self.document_tree.selection_set(valid_selection)
            if not focus or focus not in valid_selection:
                focus = valid_selection[0]
            self.document_tree.focus(focus)
            self.document_tree.see(focus)
        elif self.documents:
            first = self.documents[0].uid
            self.document_tree.selection_set(first)
            self.document_tree.focus(first)
            focus = first
        if focus:
            self.selection_anchor_uid = focus
        self.count_var.set(
            f"共 {len(self.documents)} 份 PDF"
            if self.documents
            else "尚未添加 PDF"
        )
        self._refresh_controls()

    def _selected_uids(self) -> tuple[str, ...]:
        selected = set(self.document_tree.selection())
        return tuple(
            document.uid
            for document in self.documents
            if document.uid in selected
        )

    def _selected_indices(self) -> list[int]:
        selected = set(self.document_tree.selection())
        return [
            index
            for index, document in enumerate(self.documents)
            if document.uid in selected
        ]

    def _selected_index(self) -> int | None:
        selected = set(self.document_tree.selection())
        if not selected:
            return None
        focused_uid = self.document_tree.focus()
        selected_uid = (
            focused_uid if focused_uid in selected else next(iter(selected))
        )
        for index, document in enumerate(self.documents):
            if document.uid == selected_uid:
                return index
        return None

    def _select_index(self, index: int) -> None:
        if not self.documents:
            return
        index = max(0, min(index, len(self.documents) - 1))
        uid = self.documents[index].uid
        self.document_tree.selection_set(uid)
        self.document_tree.focus(uid)
        self.document_tree.see(uid)
        self.document_tree.focus_set()
        self.selection_anchor_uid = uid
        self._refresh_controls()

    def _select_relative(self, delta: int) -> str:
        if self.busy or not self.documents:
            return "break"
        current = self._selected_index()
        if current is None:
            current = 0 if delta >= 0 else len(self.documents) - 1
        else:
            current += delta
        self._select_index(current)
        return "break"

    def _select_previous(self, _event: object) -> str:
        return self._select_relative(-1)

    def _select_next(self, _event: object) -> str:
        return self._select_relative(1)

    def _select_all(self, _event: object) -> str:
        if self.busy or not self.documents:
            return "break"
        uids = tuple(document.uid for document in self.documents)
        self.document_tree.selection_set(uids)
        focused = self.document_tree.focus()
        if focused not in uids:
            focused = uids[0]
            self.document_tree.focus(focused)
        self.selection_anchor_uid = focused
        self.document_tree.focus_set()
        self._refresh_controls()
        return "break"

    def move_selected_by(self, delta: int) -> None:
        selected_indices = self._selected_indices()
        if self.busy or not selected_indices:
            return
        selected_uids = self._selected_uids()
        focus_uid = self.document_tree.focus()
        move_documents_by(
            self.documents,
            selected_indices,
            delta,
        )
        self._refresh_tree(selected_uids, focus_uid)
        self.status_var.set(
            f"已移动 {len(selected_uids)} 份所选文档"
        )

    def move_selected_top(self) -> None:
        self._move_selected_to_edge(top=True)

    def move_selected_bottom(self) -> None:
        self._move_selected_to_edge(top=False)

    def _move_selected_to_edge(self, *, top: bool) -> None:
        selected_indices = self._selected_indices()
        if self.busy or not selected_indices:
            return
        selected_uids = self._selected_uids()
        focus_uid = self.document_tree.focus()
        move_selected_to_edge(
            self.documents,
            selected_indices,
            top=top,
        )
        self._refresh_tree(selected_uids, focus_uid)
        self.status_var.set(
            f"已将 {len(selected_uids)} 份所选文档移到"
            f"{'顶部' if top else '底部'}"
        )

    def _move_up_shortcut(self, _event: object) -> str:
        self.move_selected_by(-1)
        return "break"

    def _move_down_shortcut(self, _event: object) -> str:
        self.move_selected_by(1)
        return "break"

    def remove_selected(self) -> None:
        selected_indices = self._selected_indices()
        if self.busy or not selected_indices:
            return
        selected_set = set(selected_indices)
        first_removed = selected_indices[0]
        removed_count = len(selected_indices)
        self.documents[:] = [
            document
            for index, document in enumerate(self.documents)
            if index not in selected_set
        ]
        next_uid = None
        if self.documents:
            next_uid = self.documents[
                min(first_removed, len(self.documents) - 1)
            ].uid
        self._refresh_tree(next_uid)
        self.status_var.set(
            f"已从列表移除 {removed_count} 份 PDF，原文件未删除"
        )

    def _delete_shortcut(self, _event: object) -> str:
        self.remove_selected()
        return "break"

    def clear_documents(self) -> None:
        if self.busy or not self.documents:
            return
        if not messagebox.askyesno(
            "清空列表",
            "要从列表移除全部 PDF 吗？磁盘中的原文件不会删除。",
            parent=self.root,
        ):
            return
        self.documents.clear()
        self._refresh_tree()
        self.status_var.set("列表已清空，原文件未删除")

    def _selection_changed(self, _event: object) -> None:
        self._refresh_controls()

    def _select_clicked_row(self, row: str, state: int) -> None:
        children = tuple(self.document_tree.get_children())
        if state & SHIFT_MASK:
            anchor = self.selection_anchor_uid
            if anchor not in children:
                anchor = self.document_tree.focus() or row
            start = children.index(anchor)
            end = children.index(row)
            selected = children[min(start, end) : max(start, end) + 1]
            if state & CONTROL_MASK:
                selected = tuple(
                    dict.fromkeys(
                        (*self.document_tree.selection(), *selected)
                    )
                )
            self.document_tree.selection_set(selected)
        elif state & CONTROL_MASK:
            if row in self.document_tree.selection():
                self.document_tree.selection_remove(row)
            else:
                self.document_tree.selection_add(row)
            self.selection_anchor_uid = row
        else:
            self.document_tree.selection_set(row)
            self.selection_anchor_uid = row
        self.document_tree.focus(row)
        self.document_tree.focus_set()
        self._refresh_controls()

    def _show_marquee(
        self,
        start: tuple[int, int],
        current: tuple[int, int],
    ) -> None:
        tree_width = max(1, self.document_tree.winfo_width())
        tree_height = max(1, self.document_tree.winfo_height())
        left = max(0, min(start[0], current[0], tree_width - 1))
        right = max(
            left + 1,
            min(max(start[0], current[0]), tree_width - 1),
        )
        top = max(0, min(start[1], current[1], tree_height - 1))
        bottom = max(
            top + 1,
            min(max(start[1], current[1]), tree_height - 1),
        )
        top_edge, right_edge, bottom_edge, left_edge = (
            self.marquee_edges
        )
        top_edge.place(x=left, y=top, width=right - left, height=1)
        bottom_edge.place(
            x=left,
            y=bottom,
            width=right - left,
            height=1,
        )
        left_edge.place(x=left, y=top, width=1, height=bottom - top)
        right_edge.place(
            x=right,
            y=top,
            width=1,
            height=bottom - top,
        )
        for edge in self.marquee_edges:
            edge.lift()

    def _hide_marquee(self) -> None:
        for edge in self.marquee_edges:
            edge.place_forget()

    def _update_marquee_selection(self, x: int, y: int) -> None:
        if self.marquee_start is None:
            return
        self._show_marquee(self.marquee_start, (x, y))
        top = min(self.marquee_start[1], y)
        bottom = max(self.marquee_start[1], y)
        selected = set(self.marquee_original_selection)
        for uid in self.document_tree.get_children():
            box = self.document_tree.bbox(uid)
            if box and box[1] <= bottom and box[1] + box[3] >= top:
                selected.add(uid)
        ordered = tuple(
            document.uid
            for document in self.documents
            if document.uid in selected
        )
        self.document_tree.selection_set(ordered)
        if ordered:
            self.document_tree.focus(ordered[-1])
        self._refresh_controls()

    def _insertion_index_at(self, y: int) -> int:
        children = tuple(self.document_tree.get_children())
        for index, uid in enumerate(children):
            box = self.document_tree.bbox(uid)
            if box and y < box[1] + box[3] / 2:
                return index
        return len(children)

    def _show_drag_indicator(self, insertion_index: int) -> None:
        children = tuple(self.document_tree.get_children())
        if not children:
            return
        if insertion_index >= len(children):
            box = self.document_tree.bbox(children[-1])
            y = box[1] + box[3] if box else 0
        else:
            box = self.document_tree.bbox(children[insertion_index])
            y = box[1] if box else 0
        self.drag_indicator.place(
            x=0,
            y=max(0, y - 1),
            width=max(1, self.document_tree.winfo_width()),
            height=2,
        )
        self.drag_indicator.lift()

    def _hide_drag_indicator(self) -> None:
        self.drag_indicator.place_forget()

    def _drag_start(self, event: object) -> str | None:
        if self.busy:
            return "break"
        x = getattr(event, "x", 0)
        y = getattr(event, "y", 0)
        state = getattr(event, "state", 0)
        region = self.document_tree.identify_region(x, y)
        if region in {"heading", "separator"}:
            self.drag_uid = None
            self.drag_insert_index = None
            self.marquee_start = None
            self.marquee_original_selection = ()
            self._hide_marquee()
            self._hide_drag_indicator()
            return None
        row = self.document_tree.identify_row(y)
        if not row:
            self.drag_uid = None
            self.drag_insert_index = None
            self.marquee_start = (x, y)
            self.marquee_original_selection = (
                self._selected_uids() if state & CONTROL_MASK else ()
            )
            if not state & CONTROL_MASK:
                children = self.document_tree.get_children()
                if children:
                    self.document_tree.selection_remove(*children)
            self._show_marquee(self.marquee_start, self.marquee_start)
            self.document_tree.focus_set()
            self._refresh_controls()
            return "break"
        self._select_clicked_row(row, state)
        if state & (SHIFT_MASK | CONTROL_MASK):
            self.drag_uid = None
            return "break"
        self.drag_uid = row
        self.drag_insert_index = None
        return "break"

    def _drag_motion(self, event: object) -> str | None:
        if self.marquee_start is not None:
            self._update_marquee_selection(
                getattr(event, "x", 0),
                getattr(event, "y", 0),
            )
            return "break"
        if not self.drag_uid:
            return None
        self.drag_insert_index = self._insertion_index_at(
            getattr(event, "y", 0)
        )
        self._show_drag_indicator(self.drag_insert_index)
        self.document_tree.configure(cursor="hand2")
        return "break"

    def _drag_release(self, event: object) -> str | None:
        self.document_tree.configure(cursor="")
        if self.marquee_start is not None:
            self._update_marquee_selection(
                getattr(event, "x", 0),
                getattr(event, "y", 0),
            )
            self.marquee_start = None
            self.marquee_original_selection = ()
            self._hide_marquee()
            selected_count = len(self.document_tree.selection())
            self.status_var.set(f"已选择 {selected_count} 份 PDF")
            return "break"
        self._hide_drag_indicator()
        if not self.drag_uid:
            return None
        source_uid = self.drag_uid
        self.drag_uid = None
        insertion_index = (
            self.drag_insert_index
            if self.drag_insert_index is not None
            else self._insertion_index_at(getattr(event, "y", 0))
        )
        self.drag_insert_index = None
        source_index = next(
            index
            for index, item in enumerate(self.documents)
            if item.uid == source_uid
        )
        final_index = move_item_to_insertion(
            self.documents,
            source_index,
            insertion_index,
        )
        self._refresh_tree(source_uid)
        self.status_var.set(f"已拖动到第 {final_index + 1} 位")
        return "break"

    def _refresh_controls(self) -> None:
        if not hasattr(self, "_controls"):
            return
        selected_indices = self._selected_indices()
        has_documents = bool(self.documents)
        if self.busy:
            for control in self._controls:
                control.configure(state="disabled")
            self.document_tree.state(["disabled"])
            return
        self.document_tree.state(["!disabled"])
        self.add_files_button.configure(state="normal")
        self.add_folder_button.configure(state="normal")
        self.remove_button.configure(
            state="normal" if selected_indices else "disabled"
        )
        self.clear_button.configure(
            state="normal" if has_documents else "disabled"
        )
        self.merge_button.configure(
            state="normal" if has_documents else "disabled"
        )
        can_move_up = bool(selected_indices) and selected_indices[0] > 0
        can_move_down = (
            bool(selected_indices)
            and selected_indices[-1] < len(self.documents) - 1
        )
        self.move_top_button.configure(
            state="normal" if can_move_up else "disabled"
        )
        self.move_up_button.configure(
            state="normal" if can_move_up else "disabled"
        )
        self.move_down_button.configure(
            state="normal" if can_move_down else "disabled"
        )
        self.move_bottom_button.configure(
            state="normal" if can_move_down else "disabled"
        )

    def start_merge(self) -> None:
        if self.busy:
            return
        if not self.documents:
            messagebox.showwarning(
                "请先添加 PDF",
                "请至少添加一份 PDF 后再开始合并。",
                parent=self.root,
            )
            return
        try:
            output_path = self._reserve_desktop_output_path(
                self._desktop_directory()
            )
        except OSError:
            messagebox.showerror(
                "无法创建输出文件",
                "无法在桌面创建合并 PDF，请检查桌面目录的写入权限。",
                parent=self.root,
            )
            return
        documents = [
            MergeDocument(document.path) for document in self.documents
        ]
        self.busy = True
        self.merge_button.configure(text="正在合并…")
        self.status_var.set("正在生成文件清单和文件名称页…")
        self._refresh_controls()

        def report(current: int, total: int, title: str) -> None:
            self.root.after(
                0,
                lambda: self.status_var.set(
                    f"正在合并 {current} / {total}：{title}"
                ),
            )

        def worker() -> None:
            try:
                result = merge_pdfs(
                    documents,
                    output_path,
                    progress=report,
                )
            except Exception as exc:
                try:
                    output_path.unlink(missing_ok=True)
                except OSError:
                    pass
                self.root.after(
                    0,
                    lambda error=exc: self._merge_failed(error),
                )
                return
            self.root.after(0, lambda: self._merge_succeeded(result))

        threading.Thread(target=worker, daemon=True).start()

    @staticmethod
    def _desktop_directory() -> Path:
        if os.name == "nt":
            try:
                buffer = ctypes.create_unicode_buffer(32768)
                result = ctypes.windll.shell32.SHGetFolderPathW(
                    None,
                    0x0010,
                    None,
                    0,
                    buffer,
                )
                if result == 0 and buffer.value:
                    return Path(buffer.value)
            except (AttributeError, OSError):
                pass
        return Path.home() / "Desktop"

    @staticmethod
    def _reserve_desktop_output_path(
        desktop: Path,
        today: date | None = None,
    ) -> Path:
        desktop.mkdir(parents=True, exist_ok=True)
        date_text = (today or date.today()).strftime("%Y-%m-%d")
        base_name = f"PDF 合并输出_{date_text}"
        index = 1
        while True:
            candidate = desktop / f"{base_name}-{index:02d}.pdf"
            try:
                candidate.touch(exist_ok=False)
            except FileExistsError:
                index += 1
                continue
            return candidate

    def _merge_succeeded(self, result: object) -> None:
        self.busy = False
        self.merge_button.configure(text="开始合并")
        self._refresh_controls()
        output_path = getattr(result, "output_path")
        document_count = getattr(result, "document_count")
        self.status_var.set(f"合并完成：{output_path}")
        messagebox.showinfo(
            "合并完成",
            f"已合并 {document_count} 份 PDF。\n\n保存位置：\n{output_path}",
            parent=self.root,
        )

    def _merge_failed(self, error: Exception) -> None:
        self.busy = False
        self.merge_button.configure(text="开始合并")
        self._refresh_controls()
        message = str(error) if isinstance(error, PdfMergeError) else "合并失败，请检查所选 PDF 或桌面写入权限。"
        self.status_var.set(message)
        messagebox.showerror("无法完成合并", message, parent=self.root)

    def close(self) -> None:
        if self.busy:
            messagebox.showinfo(
                "正在合并",
                "请等待当前合并完成后再关闭软件。",
                parent=self.root,
            )
            return
        self.root.destroy()


def run() -> None:
    enable_high_dpi()
    root = Tk()
    PdfMergeApp(root)
    root.mainloop()
