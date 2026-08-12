"""Local Windows tool for merging ordered PDF documents."""

from .core import MergeDocument, MergeResult, PdfMergeError, merge_pdfs

__all__ = [
    "MergeDocument",
    "MergeResult",
    "PdfMergeError",
    "merge_pdfs",
]

__version__ = "0.1.0"
