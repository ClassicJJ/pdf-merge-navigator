from __future__ import annotations

import pytest

from pdf_merge_tool.ordering import (
    move_item,
    move_item_to_insertion,
    move_selected_by,
    move_selected_to_edge,
)


def test_move_item_keeps_the_moved_document_selected_by_index() -> None:
    documents = ["甲", "乙", "丙", "丁"]

    selected = move_item(documents, 2, 1)

    assert documents == ["甲", "丙", "乙", "丁"]
    assert selected == 1


def test_move_item_supports_top_bottom_and_clamps_target() -> None:
    documents = ["a", "b", "c"]

    assert move_item(documents, 1, -20) == 0
    assert documents == ["b", "a", "c"]
    assert move_item(documents, 0, 20) == 2
    assert documents == ["a", "c", "b"]


def test_move_item_rejects_invalid_current_index() -> None:
    with pytest.raises(IndexError):
        move_item(["a"], 2, 0)


def test_move_selected_items_preserves_group_order() -> None:
    documents = ["a", "b", "c", "d", "e"]

    selected = move_selected_by(documents, [1, 3], -1)

    assert documents == ["b", "a", "d", "c", "e"]
    assert selected == (0, 2)
    selected = move_selected_by(documents, list(selected), 1)
    assert documents == ["a", "b", "c", "d", "e"]
    assert selected == (1, 3)


def test_move_selected_items_to_edges_and_single_item_to_gap() -> None:
    documents = ["a", "b", "c", "d", "e"]

    selected = move_selected_to_edge(documents, [1, 3], top=True)

    assert documents == ["b", "d", "a", "c", "e"]
    assert selected == (0, 1)
    selected = move_selected_to_edge(
        documents,
        list(selected),
        top=False,
    )
    assert documents == ["a", "c", "e", "b", "d"]
    assert selected == (3, 4)
    assert move_item_to_insertion(documents, 1, 5) == 4
    assert documents == ["a", "e", "b", "d", "c"]
