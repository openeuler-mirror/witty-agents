"""分片写入 JSON 数组文件。"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable


class ShardWriter:
    def __init__(self, out_dir: Path, prefix: str, shard_size: int):
        self.out_dir = out_dir
        self.prefix = prefix
        self.shard_size = max(1, int(shard_size))
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self._shard_idx = 0
        self._in_shard = 0
        self._fp = None
        self.total = 0
        self.files: list[Path] = []

    def _open_new(self) -> None:
        self._close()
        self._shard_idx += 1
        path = self.out_dir / f"{self.prefix}_{self._shard_idx:04d}.json"
        self.files.append(path)
        self._fp = path.open("w", encoding="utf-8")
        self._fp.write("[\n")
        self._in_shard = 0

    def _close(self) -> None:
        if self._fp is None:
            return
        self._fp.write("\n]\n")
        self._fp.close()
        self._fp = None

    def write(self, doc: dict[str, Any]) -> None:
        if self._fp is None or self._in_shard >= self.shard_size:
            self._open_new()
        assert self._fp is not None
        if self._in_shard > 0:
            self._fp.write(",\n")
        json.dump(doc, self._fp, ensure_ascii=False, separators=(",", ":"))
        self._in_shard += 1
        self.total += 1

    def write_many(self, docs: Iterable[dict[str, Any]]) -> None:
        for d in docs:
            self.write(d)

    def close(self) -> None:
        self._close()
