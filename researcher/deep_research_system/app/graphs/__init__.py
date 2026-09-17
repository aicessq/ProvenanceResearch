from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.graphs.factory import GraphRunner

__all__ = ["GraphRunner", "build_graph_runner"]


def build_graph_runner():
    from app.graphs.factory import build_graph_runner as _build_graph_runner

    return _build_graph_runner()
