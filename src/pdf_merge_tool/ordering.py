from __future__ import annotations

from typing import TypeVar


T = TypeVar("T")


def move_item(items: list[T], current_index: int, target_index: int) -> int:
    """Move one item in place and return its final index."""
    if not 0 <= current_index < len(items):
        raise IndexError("current_index is outside the list")
    target_index = max(0, min(target_index, len(items) - 1))
    if current_index == target_index:
        return current_index
    item = items.pop(current_index)
    items.insert(target_index, item)
    return target_index


def move_selected_by(
    items: list[T],
    selected_indices: list[int],
    delta: int,
) -> tuple[int, ...]:
    """Move selected items one place while preserving their relative order."""
    if delta not in (-1, 1):
        raise ValueError("delta must be -1 or 1")
    selected = _validated_indices(items, selected_indices)
    selected_set = set(selected)
    order = selected if delta < 0 else reversed(selected)
    for index in order:
        target = index + delta
        if not 0 <= target < len(items) or target in selected_set:
            continue
        items[index], items[target] = items[target], items[index]
        selected_set.remove(index)
        selected_set.add(target)
    return tuple(sorted(selected_set))


def move_selected_to_edge(
    items: list[T],
    selected_indices: list[int],
    *,
    top: bool,
) -> tuple[int, ...]:
    """Move selected items to one edge while preserving all relative order."""
    selected = _validated_indices(items, selected_indices)
    selected_set = set(selected)
    chosen = [item for index, item in enumerate(items) if index in selected_set]
    remaining = [
        item for index, item in enumerate(items) if index not in selected_set
    ]
    items[:] = chosen + remaining if top else remaining + chosen
    start = 0 if top else len(remaining)
    return tuple(range(start, start + len(chosen)))


def move_item_to_insertion(
    items: list[T],
    source_index: int,
    insertion_index: int,
) -> int:
    """Move one item to a gap numbered from zero through ``len(items)``."""
    if not 0 <= source_index < len(items):
        raise IndexError("source_index is outside the list")
    insertion_index = max(0, min(insertion_index, len(items)))
    item = items.pop(source_index)
    if source_index < insertion_index:
        insertion_index -= 1
    items.insert(insertion_index, item)
    return insertion_index


def _validated_indices(
    items: list[T],
    selected_indices: list[int],
) -> tuple[int, ...]:
    selected = tuple(sorted(set(selected_indices)))
    if not selected:
        raise ValueError("selected_indices cannot be empty")
    if selected[0] < 0 or selected[-1] >= len(items):
        raise IndexError("selected index is outside the list")
    return selected
