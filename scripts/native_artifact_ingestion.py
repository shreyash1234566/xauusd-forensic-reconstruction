"""Safe, schema-first ingestion helpers for supplied MT4/MT5 native artifacts.

Input files are never altered.  The helpers fingerprint and inspect them before
any normalization, and classify ambiguous fields as unknown rather than
inventing an execution or quote meaning.
"""

from __future__ import annotations

import csv
import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any


TEXT_EXTENSIONS = {".csv", ".tsv", ".txt", ".log", ".html", ".htm", ".xml", ".json"}
NATIVE_EXTENSIONS = TEXT_EXTENSIONS | {".parquet"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def read_preview(path: Path, limit: int = 16_384) -> tuple[str | None, str | None]:
    """Return a decoded preview and encoding; no source content is changed."""
    if path.suffix.lower() not in TEXT_EXTENSIONS:
        return None, None
    raw = path.read_bytes()[:limit]
    for encoding in ("utf-8-sig", "utf-8", "utf-16", "cp1252", "latin-1"):
        try:
            return raw.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    return None, None


def delimiter_for(path: Path, preview: str | None) -> str | None:
    if path.suffix.lower() == ".tsv":
        return "\\t"
    if path.suffix.lower() not in {".csv", ".txt", ".log"} or not preview:
        return None
    try:
        return csv.Sniffer().sniff(preview, delimiters=",;\\t|").delimiter
    except csv.Error:
        return None


def columns_from_preview(preview: str | None, delimiter: str | None) -> list[str]:
    if not preview or not delimiter:
        return []
    first = next((line for line in preview.splitlines() if line.strip()), "")
    return [field.strip() for field in next(csv.reader([first], delimiter=delimiter), [])]


def normalized(columns: list[str]) -> set[str]:
    return {"".join(char for char in value.lower() if char.isalnum() or char == "_") for value in columns}


def classify_role(columns: list[str]) -> str:
    """Conservative file-level role classification, not field semantic proof."""
    names = normalized(columns)
    if {"bid", "ask"}.issubset(names) and ("time" in names or "timestamp" in names or "timemsc" in names):
        return "TICK_QUOTE_CANDIDATE"
    if names & {"dealticket", "dealticket", "deal", "dealid"}:
        return "DEAL_EXPORT_CANDIDATE"
    if names & {"orderticket", "order", "orderid"}:
        return "ORDER_EXPORT_CANDIDATE"
    if names & {"positionid", "position", "positionticket"}:
        return "POSITION_EXPORT_CANDIDATE"
    if {"symbol", "volume"}.issubset(names) and names & {"time", "timestamp", "open_time", "closetime"}:
        return "ACCOUNT_HISTORY_CANDIDATE"
    if not columns:
        return "UNSTRUCTURED_OR_BINARY"
    return "UNKNOWN_SCHEMA"


@dataclass(frozen=True)
class ArtifactInspection:
    path: str
    extension: str
    size_bytes: int
    sha256: str
    encoding: str | None
    delimiter: str | None
    columns: list[str]
    role: str


def inspect_artifact(path: Path) -> ArtifactInspection:
    preview, encoding = read_preview(path)
    delimiter = delimiter_for(path, preview)
    columns = columns_from_preview(preview, delimiter)
    return ArtifactInspection(
        path=str(path), extension=path.suffix.lower(), size_bytes=path.stat().st_size, sha256=sha256(path),
        encoding=encoding, delimiter=delimiter, columns=columns, role=classify_role(columns),
    )


def parse_rows_losslessly(path: Path, inspection: ArtifactInspection, row_limit: int | None = None) -> list[dict[str, Any]]:
    """Read tabular artifacts without coercing raw cells or changing the source.

    Returned values remain strings for delimited files.  Timestamp/timezone and
    price semantics are deliberately deferred to a later source-specific gate.
    """
    suffix = path.suffix.lower()
    if suffix in {".csv", ".tsv", ".txt", ".log"}:
        if not inspection.encoding or not inspection.delimiter or not inspection.columns:
            raise ValueError("Delimited artifact has no reliable header/delimiter; retain as UNKNOWN_SCHEMA")
        with path.open("r", encoding=inspection.encoding, newline="") as handle:
            reader = csv.DictReader(handle, delimiter=inspection.delimiter)
            rows: list[dict[str, Any]] = []
            for index, row in enumerate(reader, 1):
                rows.append({"_source_row": index, **{str(key): value for key, value in row.items()}})
                if row_limit is not None and len(rows) >= row_limit:
                    break
            return rows
    if suffix == ".parquet":
        import pandas as pd

        frame = pd.read_parquet(path)
        if row_limit is not None:
            frame = frame.head(row_limit)
        return [{"_source_row": index + 1, **record} for index, record in enumerate(frame.astype(object).where(frame.notna(), None).to_dict(orient="records"))]
    if suffix in {".html", ".htm"}:
        import pandas as pd

        tables = pd.read_html(path)
        rows = []
        for table_index, frame in enumerate(tables, 1):
            if row_limit is not None:
                frame = frame.head(row_limit)
            for row_index, record in enumerate(frame.astype(str).to_dict(orient="records"), 1):
                rows.append({"_table": table_index, "_source_row": row_index, **record})
        return rows
    raise ValueError(f"No lossless tabular parser for {suffix}; retain source and classify manually")


def discover_artifacts(incoming: Path) -> list[Path]:
    if not incoming.exists():
        return []
    return sorted(path for path in incoming.rglob("*") if path.is_file() and path.suffix.lower() in NATIVE_EXTENSIONS)
