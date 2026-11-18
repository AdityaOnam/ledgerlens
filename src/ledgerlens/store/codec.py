"""Lossless JSON for the frozen fact dataclasses (Decimal, date, tuples, nesting)."""

from __future__ import annotations

import dataclasses
import types
import typing
from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Any


def encode(obj: Any) -> Any:
    if dataclasses.is_dataclass(obj):
        return {f.name: encode(getattr(obj, f.name)) for f in dataclasses.fields(obj)}
    if isinstance(obj, (list, tuple)):
        return [encode(x) for x in obj]
    if isinstance(obj, Decimal):
        return str(obj)
    if isinstance(obj, date):
        return obj.isoformat()
    return obj


def decode(tp: Any, data: Any) -> Any:
    if data is None:
        return None
    origin = typing.get_origin(tp)
    if origin in (typing.Union, types.UnionType):
        inner = [a for a in typing.get_args(tp) if a is not type(None)]
        return decode(inner[0], data)
    if origin in (tuple, list):
        item = typing.get_args(tp)[0]  # tuple[X, ...] or list[X]
        seq = [decode(item, x) for x in data]
        return tuple(seq) if origin is tuple else seq
    if dataclasses.is_dataclass(tp):
        hints = typing.get_type_hints(tp)
        return tp(**{k: decode(hints[k], v) for k, v in data.items()})
    if tp is Decimal:
        return Decimal(data)
    if tp is date:
        return date.fromisoformat(data)
    if isinstance(tp, type) and issubclass(tp, Enum):
        return tp(data)
    return data
