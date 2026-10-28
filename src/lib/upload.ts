import * as XLSX from "xlsx";

export type ParsedTable = {
  columns: string[];
  rows: Record<string, string>[];
};

function parseCsv(text: string): ParsedTable {
  const rows: string[][] = [];
  let current = "";
  let row: string[] = [];
  let quoted = false;

  for (let i = 0; i < text.length; i += 1) {
    const char = text[i];
    const next = text[i + 1];
    if (char === "\"" && quoted && next === "\"") {
      current += "\"";
      i += 1;
    } else if (char === "\"") {
      quoted = !quoted;
    } else if (char === "," && !quoted) {
      row.push(current.trim());
      current = "";
    } else if ((char === "\n" || char === "\r") && !quoted) {
      if (char === "\r" && next === "\n") i += 1;
      row.push(current.trim());
      if (row.some(Boolean)) rows.push(row);
      row = [];
      current = "";
    } else {
      current += char;
    }
  }
  row.push(current.trim());
  if (row.some(Boolean)) rows.push(row);

  const columns = rows.shift()?.map((item, index) => item || `column_${index + 1}`) ?? [];
  return {
    columns,
    rows: rows.map((values) =>
      Object.fromEntries(columns.map((column, index) => [column, values[index] ?? ""]))
    )
  };
}

export async function parseUploadedTable(file: File): Promise<ParsedTable> {
  const buffer = Buffer.from(await file.arrayBuffer());
  const name = file.name.toLowerCase();

  if (name.endsWith(".csv") || file.type.includes("csv")) {
    return parseCsv(buffer.toString("utf8"));
  }

  if (name.endsWith(".xlsx") || name.endsWith(".xls") || file.type.includes("spreadsheet")) {
    const workbook = XLSX.read(buffer, { type: "buffer" });
    const firstSheet = workbook.SheetNames[0];
    const sheet = workbook.Sheets[firstSheet];
    const raw = XLSX.utils.sheet_to_json<Record<string, unknown>>(sheet, { defval: "" });
    const columns = raw.length ? Object.keys(raw[0]) : [];
    return {
      columns,
      rows: raw.map((entry) =>
        Object.fromEntries(Object.entries(entry).map(([key, value]) => [key, String(value ?? "")]))
      )
    };
  }

  throw new Error("仅支持 CSV、XLS、XLSX 文件");
}
