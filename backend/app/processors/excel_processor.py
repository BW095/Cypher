import os
import pandas as pd
from app.ingestion.canonical_document import CanonicalDocument


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
                # CSV: single-sheet, use pd.read_csv
                df = pd.read_csv(file_path)
                markdown_table = df.to_markdown(index=False)
                text_content.append(markdown_table)
                tables.append({
                    "sheet": "csv",
                    "columns": list(df.columns),
                    "data": df.to_dict(orient="records")
                })
            else:
                # Excel (.xlsx, .xls): multi-sheet support
                excel_data = pd.read_excel(file_path, sheet_name=None)

                for sheet_name, df in excel_data.items():
                    text_content.append(f"### Sheet: {sheet_name}\n")
                    markdown_table = df.to_markdown(index=False)
                    text_content.append(markdown_table)
                    text_content.append("\n")
                    tables.append({
                        "sheet": sheet_name,
                        "columns": list(df.columns),
                        "data": df.to_dict(orient="records")
                    })

        except Exception as e:
            text_content.append(f"Error processing spreadsheet: {str(e)}")

        return CanonicalDocument(
            file_path=file_path,
            file_type="spreadsheet",
            text="\n".join(text_content),
            tables=tables,
            metadata={"processor": "pandas"}
        )