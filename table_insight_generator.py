from __future__ import annotations

import tempfile
import re
from typing import BinaryIO, Dict, List, Tuple

import pandas as pd
from pathlib import Path


def read_table_file(uploaded_file: BinaryIO) -> pd.DataFrame:
    name = uploaded_file.name.lower()
    if name.endswith(".csv"):
        last_error: Exception | None = None
        for encoding in ["utf-8-sig", "utf-8", "cp1252", "latin1"]:
            try:
                uploaded_file.seek(0)
                return pd.read_csv(uploaded_file, header=None, encoding=encoding, engine="python")
            except UnicodeDecodeError as exc:
                last_error = exc
        raise RuntimeError(f"Could not read CSV encoding: {last_error}")
    if name.endswith((".xlsx", ".xls")):
        sheets = pd.read_excel(uploaded_file, header=None, sheet_name=None)
        table_sheets = [
            sheet for sheet in sheets.values()
            if find_table_starts(sheet) or parse_sperc_tables(sheet) or parse_generic_grid_tables(sheet)
        ]
        if not table_sheets:
            return next(iter(sheets.values()))
        if len(table_sheets) == 1:
            return table_sheets[0]

        normalized = []
        max_cols = max(sheet.shape[1] for sheet in table_sheets)
        for sheet in table_sheets:
            normalized_sheet = sheet.reindex(columns=range(max_cols))
            separator = pd.DataFrame([[None] * max_cols])
            normalized.extend([normalized_sheet, separator])
        return pd.concat(normalized, ignore_index=True)
    if name.endswith(".sav"):
        try:
            import pyreadstat
        except ImportError as exc:
            raise RuntimeError("SPSS .sav support needs pyreadstat in requirements.txt.") from exc

        with tempfile.NamedTemporaryFile(delete=False, suffix=".sav") as tmp:
            tmp.write(uploaded_file.getvalue())
            tmp_path = tmp.name
        try:
            df, _ = pyreadstat.read_sav(tmp_path, apply_value_formats=False)
            return df
        finally:
            Path(tmp_path).unlink(missing_ok=True)
    raise ValueError("Please upload a CSV, Excel, or SPSS .sav banner table output.")


def clean_text(value: object) -> str:
    if pd.isna(value):
        return ""
    return " ".join(str(value).replace("\n", " ").split()).strip()


def clean_theme(value: object) -> str:
    text = clean_text(value)
    if ":" in text:
        text = text.split(":", 1)[1].strip()
    for sep in [" - ", " – ", " — "]:
        if sep in text:
            text = text.split(sep, 1)[0].strip()
    return text[:80] or "Banner Table"


def numeric_pct(value: object) -> float | None:
    if isinstance(value, str):
        cleaned = value.strip().replace(",", "")
        if cleaned in {"", "-", "- ", "–", "—"}:
            return None
        cleaned = cleaned.replace("*", "")
        if cleaned.endswith("%"):
            cleaned = cleaned[:-1].strip()
        value = cleaned
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if pd.isna(number):
        return None
    if number > 100:
        return None
    if 0 <= number <= 1:
        return number * 100
    if 1 < number < 2:
        return None
    return number


def row_first_nonempty(df: pd.DataFrame, row_idx: int) -> Tuple[int, str] | None:
    for col_idx in range(df.shape[1]):
        text = clean_text(df.iat[row_idx, col_idx])
        if text:
            return col_idx, text
    return None


def row_text_from_stub(df: pd.DataFrame, row_idx: int, stub_col: int) -> str:
    text = clean_text(df.iat[row_idx, stub_col])
    if text:
        return text
    found = row_first_nonempty(df, row_idx)
    return found[1] if found else ""


def find_table_starts(df: pd.DataFrame) -> List[Tuple[int, int]]:
    starts: List[Tuple[int, int]] = []
    for idx in range(len(df)):
        found = row_first_nonempty(df, idx)
        if not found:
            continue
        col_idx, text = found
        if text.lower().startswith("table "):
            starts.append((idx, col_idx))
    return starts


def find_question_row(df: pd.DataFrame, start: int, end: int, stub_col: int) -> int | None:
    for idx in range(start + 1, min(start + 8, end)):
        text = row_text_from_stub(df, idx, stub_col)
        if text and not text.lower().startswith("table"):
            return idx
    return None


def find_base_row(df: pd.DataFrame, question_row: int, end: int, stub_col: int) -> int | None:
    for idx in range(question_row + 1, min(question_row + 18, end)):
        text = row_text_from_stub(df, idx, stub_col).lower()
        if text.startswith("base"):
            return idx
    return None


def banner_labels(df: pd.DataFrame, question_row: int, base_row: int, stub_col: int) -> Dict[int, str]:
    labels: Dict[int, str] = {}
    header_rows = []
    for idx in range(question_row + 1, base_row):
        row_values = [clean_text(value) for value in df.iloc[idx, stub_col + 1:].tolist()]
        non_empty = [value for value in row_values if value]
        if not non_empty:
            continue
        code_like = sum(1 for value in non_empty if value.startswith("(") and value.endswith(")"))
        if code_like >= max(1, len(non_empty) // 2):
            continue
        header_rows.append(idx)

    label_row = header_rows[-1] if header_rows else None
    group_row = header_rows[-2] if len(header_rows) >= 2 else None

    current_group = ""
    for col in range(stub_col + 1, df.shape[1]):
        group = clean_text(df.iat[group_row, col]) if group_row is not None else ""
        if group:
            current_group = group
        label = clean_text(df.iat[label_row, col]) if label_row is not None else ""

        parts = []
        if current_group and current_group.lower() != label.lower():
            parts.append(current_group)
        if label:
            parts.append(label)
        labels[col] = " - ".join(parts) if parts else f"Column {col + 1}"

    return labels


def valid_attribute(text: str) -> bool:
    lowered = text.lower()
    if not text:
        return False
    if lowered.startswith("base") or lowered.startswith("unweighted"):
        return False
    if lowered.startswith("proportions/means") or lowered.startswith("go to index"):
        return False
    if lowered.startswith("* small base") or set(lowered) == {"_"}:
        return False
    if lowered in {"sigma", "sig", "significance"}:
        return False
    if lowered.startswith("sig "):
        return False
    if lowered in {"total", "sum", "tw", "jp", "mx"}:
        return False
    if lowered in {"1", "0"}:
        return False
    return True


def parse_table_block(df: pd.DataFrame, start: int, end: int, stub_col: int) -> Dict[str, object] | None:
    question_row = find_question_row(df, start, end, stub_col)
    if question_row is None:
        return None
    base_row = find_base_row(df, question_row, end, stub_col)
    if base_row is None:
        return None

    question = row_text_from_stub(df, question_row, stub_col)
    labels = banner_labels(df, question_row, base_row, stub_col)

    rows = []
    for idx in range(base_row + 1, end):
        attribute = clean_text(df.iat[idx, stub_col])
        if not valid_attribute(attribute):
            continue
        values = {}
        for col, banner in labels.items():
            pct = numeric_pct(df.iat[idx, col])
            if pct is not None:
                values[banner] = pct
        if values:
            rows.append({"attribute": attribute, "values": values})

    if not rows:
        return None

    return {
        "table": row_text_from_stub(df, start, stub_col),
        "question": question,
        "theme": clean_theme(question),
        "rows": rows,
    }


def row_has_text(df: pd.DataFrame, row_idx: int, text: str) -> bool:
    target = text.lower()
    return any(target in clean_text(value).lower() for value in df.iloc[row_idx].tolist())


def is_code_row(values: List[str]) -> bool:
    non_empty = [value for value in values if value]
    if not non_empty:
        return False
    code_like = sum(1 for value in non_empty if re.fullmatch(r"[A-Za-z]", value))
    return code_like >= max(2, len(non_empty) // 2)


def find_sperc_starts(df: pd.DataFrame) -> List[Tuple[int, int]]:
    starts: List[Tuple[int, int]] = []
    for idx in range(len(df) - 1):
        found = row_first_nonempty(df, idx)
        if not found:
            continue
        stub_col, question = found
        lowered = question.lower()
        next_text = clean_text(df.iat[idx + 1, stub_col]).lower()
        if (
            next_text.startswith("base")
            and "hidden" not in lowered
            and not lowered.startswith(("base", "go to index", "proportions/means"))
        ):
            starts.append((idx, stub_col))
    return starts


def sperc_banner_labels(df: pd.DataFrame, stub_col: int, header_start: int, total_row: int) -> Dict[int, str]:
    header_rows = []
    for idx in range(header_start, total_row):
        values = [clean_text(value) for value in df.iloc[idx, stub_col + 1:].tolist()]
        if not any(values) or is_code_row(values):
            continue
        header_rows.append(idx)

    group_row = header_rows[0] if header_rows else None
    label_row = header_rows[1] if len(header_rows) > 1 else None
    labels: Dict[int, str] = {}
    current_group = ""
    for col in range(stub_col + 1, df.shape[1]):
        group = clean_text(df.iat[group_row, col]) if group_row is not None else ""
        if group:
            current_group = group
        label = clean_text(df.iat[label_row, col]) if label_row is not None else ""

        if current_group and label and current_group.lower() != label.lower():
            labels[col] = f"{current_group} - {label}"
        elif label:
            labels[col] = label
        elif current_group:
            labels[col] = current_group
        else:
            labels[col] = f"Column {col + 1}"
    return labels


def parse_sperc_block(df: pd.DataFrame, start: int, end: int, stub_col: int, table_number: int) -> Dict[str, object] | None:
    question = row_text_from_stub(df, start, stub_col)
    total_row = None
    for idx in range(start + 2, min(start + 10, end)):
        if clean_text(df.iat[idx, stub_col]).lower() == "total":
            total_row = idx
            break
    if total_row is None:
        return None

    labels = sperc_banner_labels(df, stub_col, start + 2, total_row)
    rows = []
    for idx in range(total_row + 1, end):
        attribute = clean_text(df.iat[idx, stub_col])
        if row_has_text(df, idx, "Proportions/Means") or row_has_text(df, idx, "Go to Index"):
            break
        if not valid_attribute(attribute):
            continue
        values = {}
        for col, banner in labels.items():
            pct = numeric_pct(df.iat[idx, col])
            if pct is not None:
                values[banner] = pct
        if values:
            rows.append({"attribute": attribute, "values": values})

    if not rows:
        return None

    return {
        "table": f"SPERC Table {table_number}",
        "question": question,
        "theme": clean_theme(question),
        "rows": rows,
    }


def parse_sperc_tables(df: pd.DataFrame) -> List[Dict[str, object]]:
    starts = find_sperc_starts(df)
    tables = []
    for pos, (start, stub_col) in enumerate(starts, start=1):
        end = starts[pos][0] if pos < len(starts) else len(df)
        parsed = parse_sperc_block(df, start, end, stub_col, pos)
        if parsed:
            tables.append(parsed)
    return tables


def row_numeric_values(df: pd.DataFrame, row_idx: int, stub_col: int) -> Dict[int, float]:
    values = {}
    for col in range(stub_col + 1, df.shape[1]):
        pct = numeric_pct(df.iat[row_idx, col])
        if pct is not None:
            values[col] = pct
    return values


def infer_column_label(df: pd.DataFrame, data_row: int, col: int) -> str:
    parts: List[str] = []
    for idx in range(max(0, data_row - 8), data_row):
        text = clean_text(df.iat[idx, col])
        if not text:
            continue
        if numeric_pct(text) is not None:
            continue
        lowered = text.lower()
        if lowered.startswith("base") or lowered in {"sigma", "sig", "significance", "1", "0"}:
            continue
        if text.startswith("(") and text.endswith(")"):
            continue
        if text not in parts:
            parts.append(text)
    if parts:
        return " - ".join(parts[-2:])
    return f"Column {col + 1}"


def infer_generic_question(df: pd.DataFrame, first_row: int, stub_col: int) -> str:
    for idx in range(first_row - 1, max(-1, first_row - 14), -1):
        text = row_text_from_stub(df, idx, stub_col)
        if not text:
            continue
        lowered = text.lower()
        if lowered in {"answer", "answers", "attribute", "attributes", "response", "responses", "label", "labels"}:
            continue
        if lowered.startswith("base") or lowered.startswith("table"):
            continue
        numeric_count = len(row_numeric_values(df, idx, stub_col))
        if numeric_count < 2 and valid_attribute(text):
            return text
    return "Uploaded Table"


def parse_generic_grid_tables(df: pd.DataFrame) -> List[Dict[str, object]]:
    data_rows = []
    for idx in range(len(df)):
        found = row_first_nonempty(df, idx)
        if not found:
            continue
        stub_col, attribute = found
        if not valid_attribute(attribute):
            continue
        values_by_col = row_numeric_values(df, idx, stub_col)
        if len(values_by_col) >= 2:
            values = {infer_column_label(df, idx, col): pct for col, pct in values_by_col.items()}
            data_rows.append({"idx": idx, "stub_col": stub_col, "attribute": attribute, "values": values})

    if not data_rows:
        return []

    groups = []
    current = [data_rows[0]]
    for row in data_rows[1:]:
        previous = current[-1]
        if row["idx"] - previous["idx"] <= 3 and row["stub_col"] == previous["stub_col"]:
            current.append(row)
        else:
            groups.append(current)
            current = [row]
    groups.append(current)

    tables: List[Dict[str, object]] = []
    for pos, group in enumerate(groups, start=1):
        stub_col = int(group[0]["stub_col"])
        first_row = int(group[0]["idx"])
        question = infer_generic_question(df, first_row, stub_col)
        rows = [{"attribute": row["attribute"], "values": row["values"]} for row in group]
        if rows:
            tables.append(
                {
                    "table": f"Table {pos}",
                    "question": question,
                    "theme": clean_theme(question),
                    "rows": rows,
                }
            )
    return tables


def top_total_insight(insight_id: str, table: Dict[str, object]) -> Dict[str, str] | None:
    rows = table["rows"]
    total_candidates = []
    for row in rows:
        values = row["values"]
        total_key = next((key for key in values if key.lower().startswith("total")), None)
        if total_key:
            total_candidates.append((row["attribute"], values[total_key], total_key))
    if not total_candidates:
        return None

    attribute, pct, total_key = max(total_candidates, key=lambda item: item[1])
    theme = str(table["theme"])
    question = str(table["question"])
    return {
        "insight_id": insight_id,
        "theme": theme,
        "insight_text": f"For {theme}, {attribute} is the leading overall response at {pct:.1f}%.",
        "evidence_note": f"{table['table']} {question}: {attribute} among {total_key}={pct:.1f}%.",
    }


def standout_banner_insight(insight_id: str, table: Dict[str, object]) -> Dict[str, str] | None:
    best = None
    for row in table["rows"]:
        values = row["values"]
        total_key = next((key for key in values if key.lower().startswith("total")), None)
        total = values.get(total_key) if total_key else None
        for banner, pct in values.items():
            if total_key and banner == total_key:
                continue
            diff = pct - total if total is not None else pct
            candidate = (diff, pct, row["attribute"], banner, total)
            if best is None or candidate[0] > best[0]:
                best = candidate

    if best is None:
        return None

    diff, pct, attribute, banner, total = best
    theme = str(table["theme"])
    question = str(table["question"])
    if total is not None and abs(diff) >= 5:
        text = f"For {theme}, {banner} over-indexes on {attribute} at {pct:.1f}%, compared with {total:.1f}% overall."
        evidence = f"{table['table']} {question}: {attribute} among {banner}={pct:.1f}% vs Total={total:.1f}%."
    else:
        text = f"For {theme}, {banner} shows the strongest response on {attribute} at {pct:.1f}%."
        evidence = f"{table['table']} {question}: {attribute} among {banner}={pct:.1f}%."

    return {
        "insight_id": insight_id,
        "theme": f"{theme} by Banner",
        "insight_text": text,
        "evidence_note": evidence,
    }


def low_banner_insight(insight_id: str, table: Dict[str, object]) -> Dict[str, str] | None:
    weakest = None
    for row in table["rows"]:
        values = row["values"]
        total_key = next((key for key in values if key.lower().startswith("total")), None)
        total = values.get(total_key) if total_key else None
        if total is None:
            continue
        for banner, pct in values.items():
            if banner == total_key:
                continue
            diff = pct - total
            candidate = (diff, pct, row["attribute"], banner, total)
            if weakest is None or candidate[0] < weakest[0]:
                weakest = candidate

    if weakest is None or weakest[0] > -5:
        return None

    diff, pct, attribute, banner, total = weakest
    theme = str(table["theme"])
    question = str(table["question"])
    return {
        "insight_id": insight_id,
        "theme": f"{theme} Gap",
        "insight_text": f"For {theme}, {banner} under-indexes on {attribute} at {pct:.1f}%, compared with {total:.1f}% overall.",
        "evidence_note": f"{table['table']} {question}: {attribute} among {banner}={pct:.1f}% vs Total={total:.1f}%.",
    }


def parse_banner_tables(df: pd.DataFrame) -> List[Dict[str, object]]:
    starts = find_table_starts(df)
    tables = []
    for pos, (start, stub_col) in enumerate(starts):
        end = starts[pos + 1][0] if pos + 1 < len(starts) else len(df)
        parsed = parse_table_block(df, start, end, stub_col)
        if parsed:
            tables.append(parsed)
    if tables:
        return tables
    sperc_tables = parse_sperc_tables(df)
    if sperc_tables:
        return sperc_tables
    return parse_generic_grid_tables(df)


def add_story_insights(insights: List[Dict[str, str]], tables: List[Dict[str, object]]) -> None:
    if not insights:
        return
    themes = []
    for item in insights:
        theme = item["theme"]
        if theme not in themes and "Gap" not in theme and "by Banner" not in theme:
            themes.append(theme)
        if len(themes) >= 5:
            break

    insights.append(
        {
            "insight_id": f"BT-{len(insights) + 1:03d}",
            "theme": "Overall Summary",
            "insight_text": f"Across {len(tables)} banner tables, the analysis produced {len(insights)} question-level and banner-cut insights, with early themes including {', '.join(themes)}.",
            "evidence_note": f"Based on {len(tables)} parsed banner tables and {len(insights)} generated insights.",
        }
    )
    insights.append(
        {
            "insight_id": f"BT-{len(insights) + 1:03d}",
            "theme": "Complete Story",
            "insight_text": "The banner-table story highlights the leading response patterns for each question and identifies where specific audience cuts over-index or under-index versus the total sample.",
            "evidence_note": f"Story synthesized from {len(tables)} banner tables using total responses and banner-cut comparisons.",
        }
    )


def generate_insights_from_table(table_df: pd.DataFrame) -> pd.DataFrame:
    tables = parse_banner_tables(table_df)
    insights: List[Dict[str, str]] = []

    for table in tables:
        for builder in [top_total_insight, standout_banner_insight, low_banner_insight]:
            insight = builder(f"BT-{len(insights) + 1:03d}", table)
            if insight:
                insights.append(insight)

    return pd.DataFrame(insights)
