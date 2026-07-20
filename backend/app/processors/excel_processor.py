import os
import pandas as pd
from app.ingestion.canonical_document import CanonicalDocument

# Sheets larger than this are summarized (schema + stats + sample) instead of
# being serialized row-by-row. A 43,200-row sensor log otherwise becomes
# thousands of embedding chunks of raw numbers — slow to embed and useless for
# semantic retrieval. A statistical summary answers "what was the max bearing
# temp for COMP-302?" far better than 2,800 embedded rows.
SUMMARY_ROW_THRESHOLD = int(os.getenv("SPREADSHEET_SUMMARY_ROWS", "150"))
SAMPLE_HEAD = 15
SAMPLE_TAIL = 5


class ExcelProcessor:
    def __init__(self):
        pass

    def process(self, file_path: str) -> CanonicalDocument:
        print(f"Processing Spreadsheet: {file_path}")

        file_ext = os.path.splitext(file_path)[1].lower()
        text_content = []
        tables = []

        try:
            if file_ext == ".csv":
                sheets = {"csv": pd.read_csv(file_path)}
            else:
                sheets = pd.read_excel(file_path, sheet_name=None)

            for sheet_name, df in sheets.items():
                text_content.append(self._render_sheet(sheet_name, df))
                text_content.append("")
                # Keep a bounded sample in metadata (never the full 40k rows).
                sample = df.head(SAMPLE_HEAD)
                tables.append({
                    "sheet": sheet_name,
                    "columns": [str(c) for c in df.columns],
                    "row_count": int(df.shape[0]),
                    "data": sample.to_dict(orient="records"),
                })

        except Exception as e:
            text_content.append(f"Error processing spreadsheet: {str(e)}")

        return CanonicalDocument(
            file_path=file_path,
            file_type="spreadsheet",
            text="\n".join(text_content),
            tables=tables,
            metadata={"processor": "pandas"},
        )

    def _render_sheet(self, sheet_name: str, df: pd.DataFrame) -> str:
        """Full markdown for small sheets; a compact summary for large ones."""
        if df.shape[0] <= SUMMARY_ROW_THRESHOLD:
            return f"### Sheet: {sheet_name}\n{df.to_markdown(index=False)}\n"
        return self._summarize_sheet(sheet_name, df)

    def _summarize_sheet(self, sheet_name: str, df: pd.DataFrame) -> str:
        """Schema + per-column stats + a head/tail sample — a handful of
        semantically rich lines instead of thousands of raw-row chunks."""
        rows, cols = df.shape
        parts = [
            f"### Sheet: {sheet_name}",
            f"Tabular data: {rows:,} rows × {cols} columns "
            f"(summarized — full row-by-row data not embedded).",
            f"Columns: {', '.join(str(c) for c in df.columns)}.",
        ]

        # Time span, if any column parses as datetimes.
        for col in df.columns:
            try:
                ts = pd.to_datetime(df[col], errors="raise")
                parts.append(f"'{col}' spans {ts.min()} to {ts.max()}.")
                break
            except (ValueError, TypeError):
                continue

        # Numeric column ranges — the useful, queryable signal.
        num = df.select_dtypes(include="number")
        for col in num.columns:
            s = num[col].dropna()
            if s.empty:
                continue
            parts.append(
                f"{col}: min {s.min():.4g}, max {s.max():.4g}, "
                f"mean {s.mean():.4g}, std {s.std():.4g}."
            )

        # Categorical columns — top values (e.g. Equipment_ID).
        for col in df.select_dtypes(include=["object", "category"]).columns:
            vc = df[col].astype(str).value_counts().head(10)
            if len(vc):
                parts.append(
                    f"{col} values: "
                    + ", ".join(f"{k} ({v})" for k, v in vc.items())
                )

        # A small sample so exact tags/values still appear in the text.
        sample = pd.concat([df.head(SAMPLE_HEAD), df.tail(SAMPLE_TAIL)])
        parts.append("Sample rows:\n" + sample.to_markdown(index=False))
        return "\n".join(parts)
