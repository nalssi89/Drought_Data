const fs = require("fs");
const path = require("path");
const { TextDecoder } = require("util");

const inputs = [
  {
    label: "2001_2010",
    source: "C:/Users/user/Downloads/CLM_SPI_DD_20260427163903.csv",
  },
  {
    label: "2011_2020",
    source: "C:/Users/user/Downloads/CLM_SPI_DD_20260427164047.csv",
  },
  {
    label: "2021_2026",
    source: "C:/Users/user/Downloads/CLM_SPI_DD_20260427171016.csv",
  },
];

const outDir = path.resolve("outputs/spi_original_markdown_archive");
const decoder = new TextDecoder("windows-949");

function csvLineCount(text) {
  if (!text) return 0;
  const normalized = text.endsWith("\n") ? text.slice(0, -1) : text;
  return normalized ? normalized.split(/\r?\n/).length : 0;
}

function firstDataDate(text) {
  const line = text.split(/\r?\n/).find((item, index) => index > 0 && item.trim());
  return line ? line.split(",")[2] : "";
}

function lastDataDate(text) {
  const lines = text.trimEnd().split(/\r?\n/);
  for (let i = lines.length - 1; i >= 1; i -= 1) {
    if (lines[i].trim()) return lines[i].split(",")[2];
  }
  return "";
}

function stationCount(text) {
  const stations = new Set();
  for (const line of text.trimEnd().split(/\r?\n/).slice(1)) {
    if (!line.trim()) continue;
    stations.add(line.split(",")[0]);
  }
  return stations.size;
}

function writeArchive(input) {
  const csvText = decoder.decode(fs.readFileSync(input.source)).replace(/\r\n/g, "\n");
  const dataRows = Math.max(0, csvLineCount(csvText) - 1);
  const mdName = `CLM_SPI_DD_${input.label}.md`;
  const mdPath = path.join(outDir, mdName);
  const body = [
    `# CLM SPI 일자료 원본 백업 (${input.label.replace("_", "-")})`,
    "",
    `- 원본 파일명: \`${path.basename(input.source)}\``,
    "- 원본 인코딩: CP949/Windows 한글",
    "- 백업 형식: UTF-8 Markdown 안의 CSV 코드블록",
    `- 컬럼: 지점, 지점명, 일시, SPI3, SPI6`,
    `- 자료 기간: ${firstDataDate(csvText)} ~ ${lastDataDate(csvText)}`,
    `- 지점 수: ${stationCount(csvText)}`,
    `- 자료 행 수: ${dataRows}`,
    "",
    "```csv",
    csvText.trimEnd(),
    "```",
    "",
  ].join("\n");
  fs.writeFileSync(mdPath, "\uFEFF" + body, "utf8");
  return { mdName, mdPath, dataRows, stations: stationCount(csvText), firstDate: firstDataDate(csvText), lastDate: lastDataDate(csvText) };
}

function main() {
  fs.mkdirSync(outDir, { recursive: true });
  const archives = inputs.map(writeArchive);
  const indexLines = [
    "# SPI3/SPI6 원본 Markdown 백업 색인",
    "",
    "CSV 원본이 내부망 PC 재부팅 등으로 삭제될 경우를 대비해, 다운로드 CSV 내용을 Markdown 파일에 보존했습니다.",
    "",
    "| 파일 | 기간 | 지점 수 | 자료 행 수 |",
    "|---|---:|---:|---:|",
    ...archives.map((item) => `| [${item.mdName}](./${item.mdName}) | ${item.firstDate} ~ ${item.lastDate} | ${item.stations} | ${item.dataRows} |`),
    "",
    "복원할 때는 각 Markdown 파일의 `csv` 코드블록 내용을 그대로 `.csv` 파일로 저장하면 됩니다.",
    "",
  ];
  fs.writeFileSync(path.join(outDir, "README.md"), "\uFEFF" + indexLines.join("\n"), "utf8");

  console.log(`outDir=${outDir}`);
  for (const item of archives) {
    console.log(`${item.mdName}: rows=${item.dataRows}, stations=${item.stations}, range=${item.firstDate}..${item.lastDate}`);
  }
}

main();
