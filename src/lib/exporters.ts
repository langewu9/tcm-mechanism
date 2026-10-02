import { existsSync } from "node:fs";
import PDFDocument from "pdfkit";

function resolvePdfFont() {
  const candidates = [
    process.env.PDF_FONT_PATH,
    "C:\\Windows\\Fonts\\NotoSansSC-VF.ttf",
    "C:\\Windows\\Fonts\\simhei.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"
  ];
  return candidates.find((item): item is string => Boolean(item && existsSync(item)));
}

export function toCsv(rows: Record<string, unknown>[]) {
  if (!rows.length) return "";
  const columns = Object.keys(rows[0]);
  const escape = (value: unknown) => {
    const text = String(value ?? "");
    return /[",\n\r]/.test(text) ? `"${text.replaceAll("\"", "\"\"")}"` : text;
  };
  return [columns.join(","), ...rows.map((row) => columns.map((column) => escape(row[column])).join(","))].join("\n");
}

export function buildPdf(title: string, lines: string[]) {
  return new Promise<Buffer>((resolve, reject) => {
    try {
      const doc = new PDFDocument({ margin: 48, size: "A4" });
      const chunks: Buffer[] = [];
      doc.on("data", (chunk: Buffer) => chunks.push(chunk));
      doc.on("end", () => resolve(Buffer.concat(chunks)));
      doc.on("error", reject);

      const fontPath = resolvePdfFont();
      if (fontPath) doc.font(fontPath);

      doc.fontSize(18).text(title);
      doc.moveDown();
      lines.forEach((line) => {
        doc.fontSize(11).text(line, { width: 500 });
        doc.moveDown(0.4);
      });
      doc.end();
    } catch (error) {
      reject(error);
    }
  });
}
