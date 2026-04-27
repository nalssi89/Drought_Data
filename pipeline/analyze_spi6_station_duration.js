const fs = require("fs");
const path = require("path");
const { TextDecoder } = require("util");

const inputPaths = [
  "C:/Users/user/Downloads/CLM_SPI_DD_20260427163903.csv",
  "C:/Users/user/Downloads/CLM_SPI_DD_20260427164047.csv",
  "C:/Users/user/Downloads/CLM_SPI_DD_20260427171016.csv",
];

const outDir = path.resolve("outputs/spi6_station_duration_analysis");
const decoder = new TextDecoder("windows-949");

const levels = [
  { key: "interest", ko: "관심", threshold: -1.0 },
  { key: "caution", ko: "주의", threshold: -1.5 },
  { key: "alert", ko: "경계", threshold: -2.0 },
  { key: "serious", ko: "심각", threshold: -2.0, minDuration: 20 },
];

function parseNumber(text) {
  if (!text || !text.trim()) return null;
  const value = Number(text.trim());
  return Number.isFinite(value) ? value : null;
}

function parseDate(dateText) {
  const [year, month, day] = dateText.split("-").map(Number);
  return new Date(Date.UTC(year, month - 1, day));
}

function formatDate(date) {
  return date.toISOString().slice(0, 10);
}

function nextEffectiveDate(dateText) {
  const date = parseDate(dateText);
  date.setUTCDate(date.getUTCDate() + 1);
  if (formatDate(date).slice(5) === "02-29") {
    date.setUTCDate(date.getUTCDate() + 1);
  }
  return formatDate(date);
}

function isConsecutive(prevDate, nextDate) {
  return nextEffectiveDate(prevDate) === nextDate;
}

function csvEscape(value) {
  const text = String(value ?? "");
  return /[",\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

function writeCsv(filePath, rows, columns) {
  fs.writeFileSync(
    filePath,
    [columns.join(","), ...rows.map((row) => columns.map((col) => csvEscape(row[col])).join(","))].join("\n") + "\n",
    "utf8",
  );
}

function readRows() {
  const rows = [];
  for (const inputPath of inputPaths) {
    const text = decoder.decode(fs.readFileSync(inputPath));
    const lines = text.trimEnd().split(/\r?\n/).slice(1);
    for (const line of lines) {
      if (!line.trim()) continue;
      const [stationCode, stationName, date, , spi6] = line.split(",").map((value) => value.trim());
      rows.push({
        station_code: stationCode,
        station_name: stationName,
        date,
        spi6: parseNumber(spi6),
      });
    }
  }
  rows.sort((a, b) => Number(a.station_code) - Number(b.station_code) || a.date.localeCompare(b.date));
  return rows;
}

function buildEpisodesForThreshold(stationRows, level) {
  const episodes = [];
  let current = null;

  for (const row of stationRows) {
    const active = row.spi6 !== null && row.spi6 <= level.threshold;
    const continuous = current && isConsecutive(current.end_date, row.date);

    if (!active || !continuous) {
      if (current) episodes.push(current);
      current = null;
    }

    if (active) {
      if (!current) {
        current = {
          level_key: level.key,
          level_ko: level.ko,
          threshold: level.threshold,
          station_code: row.station_code,
          station_name: row.station_name,
          start_date: row.date,
          end_date: row.date,
          duration: 1,
          min_spi6: row.spi6,
        };
      } else {
        current.end_date = row.date;
        current.duration += 1;
        current.min_spi6 = Math.min(current.min_spi6, row.spi6);
      }
    }
  }

  if (current) episodes.push(current);
  if (level.minDuration) return episodes.filter((episode) => episode.duration >= level.minDuration);
  return episodes;
}

function droughtClass(value) {
  if (value === null) return "결측";
  if (value >= 1.0) return "습함";
  if (value >= -0.99) return "정상";
  if (value >= -1.49) return "관심";
  if (value >= -1.99) return "주의";
  return "경계";
}

function buildStationSummary(rows) {
  const byStation = new Map();
  for (const row of rows) {
    const key = `${row.station_code}|${row.station_name}`;
    if (!byStation.has(key)) byStation.set(key, []);
    byStation.get(key).push(row);
  }

  const allEpisodes = [];
  const summaryRows = [];

  for (const [key, stationRows] of byStation.entries()) {
    const [stationCode, stationName] = key.split("|");
    stationRows.sort((a, b) => a.date.localeCompare(b.date));
    const latest = stationRows[stationRows.length - 1];
    const row = {
      station_code: stationCode,
      station_name: stationName,
      first_date: stationRows[0].date,
      last_date: latest.date,
      data_days: stationRows.length,
      latest_spi6: latest.spi6,
      latest_stage: droughtClass(latest.spi6),
      worst_spi6: Math.min(...stationRows.map((item) => item.spi6).filter((value) => value !== null)),
    };

    for (const level of levels) {
      const episodes = buildEpisodesForThreshold(stationRows, level);
      allEpisodes.push(...episodes);
      const totalDays = episodes.reduce((sum, episode) => sum + episode.duration, 0);
      const maxEpisode = [...episodes].sort((a, b) => b.duration - a.duration)[0];
      row[`${level.key}_episodes`] = episodes.length;
      row[`${level.key}_total_days`] = totalDays;
      row[`${level.key}_max_days`] = maxEpisode ? maxEpisode.duration : 0;
      row[`${level.key}_max_period`] = maxEpisode ? `${maxEpisode.start_date}~${maxEpisode.end_date}` : "";
      row[`${level.key}_worst_spi6`] = episodes.length ? Math.min(...episodes.map((episode) => episode.min_spi6)) : "";
    }

    summaryRows.push(row);
  }

  summaryRows.sort((a, b) => Number(a.station_code) - Number(b.station_code));
  allEpisodes.sort(
    (a, b) =>
      a.level_key.localeCompare(b.level_key) ||
      Number(a.station_code) - Number(b.station_code) ||
      a.start_date.localeCompare(b.start_date),
  );
  return { summaryRows, allEpisodes };
}

function svgHeader(width, height) {
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}">`;
}

function stationHeatmap(summaryRows) {
  const width = 1120;
  const height = 1900;
  const margin = { top: 88, right: 80, bottom: 42, left: 128 };
  const cellW = 190;
  const cellH = 23;
  const gap = 2;
  const keys = ["interest", "caution", "alert", "serious"];
  const labels = ["관심", "주의", "경계", "심각"];
  const maxValue = Math.max(...summaryRows.flatMap((row) => keys.map((key) => row[`${key}_total_days`])));

  let svg = svgHeader(width, height);
  svg += `<rect width="100%" height="100%" fill="#ffffff"/>`;
  svg += `<text x="${width / 2}" y="34" text-anchor="middle" font-family="Arial, sans-serif" font-size="23" font-weight="700">66개 지점별 SPI6 가뭄 지속일수</text>`;
  svg += `<text x="${width / 2}" y="60" text-anchor="middle" font-family="Arial, sans-serif" font-size="13" fill="#555">숫자는 각 임계값 이하 지속구간의 누적일수. 심각은 SPI6<=-2.00이 20일 이상 지속된 구간</text>`;
  labels.forEach((label, i) => {
    const x = margin.left + i * (cellW + 18);
    svg += `<text x="${x + cellW / 2}" y="${margin.top - 16}" text-anchor="middle" font-family="Arial, sans-serif" font-size="13" font-weight="700">${label}</text>`;
  });

  summaryRows.forEach((row, r) => {
    const y = margin.top + r * (cellH + gap);
    svg += `<text x="${margin.left - 10}" y="${y + 16}" text-anchor="end" font-family="Arial, sans-serif" font-size="12">${row.station_code} ${row.station_name}</text>`;
    keys.forEach((key, c) => {
      const x = margin.left + c * (cellW + 18);
      const value = row[`${key}_total_days`];
      const alpha = value ? 0.12 + 0.78 * (value / maxValue) : 0.03;
      svg += `<rect x="${x}" y="${y}" width="${cellW}" height="${cellH}" fill="rgba(239,68,68,${alpha.toFixed(3)})" stroke="#fff"/>`;
      svg += `<text x="${x + cellW / 2}" y="${y + 16}" text-anchor="middle" font-family="Arial, sans-serif" font-size="11" fill="${alpha > 0.54 ? "#fff" : "#111"}">${value ? value.toLocaleString() : ""}</text>`;
    });
  });

  svg += `<text x="${width / 2}" y="${height - 14}" text-anchor="middle" font-family="Arial, sans-serif" font-size="12" fill="#666">윤일은 연속으로 처리, 그 외 누락일은 지속구간을 끊음</text>`;
  svg += `</svg>`;
  return svg;
}

function topStationBars(summaryRows, key, title, fileLabel) {
  const rows = [...summaryRows]
    .sort((a, b) => b[`${key}_total_days`] - a[`${key}_total_days`])
    .slice(0, 20);
  const width = 1040;
  const height = 680;
  const margin = { top: 76, right: 130, bottom: 46, left: 130 };
  const barH = 22;
  const gap = 7;
  const maxValue = Math.max(...rows.map((row) => row[`${key}_total_days`]), 1);

  let svg = svgHeader(width, height);
  svg += `<rect width="100%" height="100%" fill="#ffffff"/>`;
  svg += `<text x="${width / 2}" y="34" text-anchor="middle" font-family="Arial, sans-serif" font-size="23" font-weight="700">${title}</text>`;
  svg += `<text x="${width / 2}" y="58" text-anchor="middle" font-family="Arial, sans-serif" font-size="13" fill="#555">${fileLabel}</text>`;
  rows.forEach((row, i) => {
    const y = margin.top + i * (barH + gap);
    const value = row[`${key}_total_days`];
    const w = (value / maxValue) * (width - margin.left - margin.right);
    svg += `<text x="${margin.left - 10}" y="${y + 16}" text-anchor="end" font-family="Arial, sans-serif" font-size="12">${row.station_code} ${row.station_name}</text>`;
    svg += `<rect x="${margin.left}" y="${y}" width="${w}" height="${barH}" rx="4" fill="#dc2626"/>`;
    svg += `<text x="${margin.left + w + 8}" y="${y + 16}" font-family="Arial, sans-serif" font-size="12">${value.toLocaleString()}일 / 최장 ${row[`${key}_max_days`]}일</text>`;
  });
  svg += `</svg>`;
  return svg;
}

function latestStageChart(summaryRows) {
  const counts = {};
  for (const row of summaryRows) counts[row.latest_stage] = (counts[row.latest_stage] || 0) + 1;
  const order = ["습함", "정상", "관심", "주의", "경계", "결측"];
  const colors = { 습함: "#2563eb", 정상: "#9ca3af", 관심: "#f59e0b", 주의: "#ef4444", 경계: "#991b1b", 결측: "#111827" };
  const width = 760;
  const height = 360;
  const margin = { top: 76, right: 60, bottom: 50, left: 70 };
  const maxValue = Math.max(...order.map((key) => counts[key] || 0), 1);
  const barW = 78;
  const gap = 22;

  let svg = svgHeader(width, height);
  svg += `<rect width="100%" height="100%" fill="#ffffff"/>`;
  svg += `<text x="${width / 2}" y="34" text-anchor="middle" font-family="Arial, sans-serif" font-size="23" font-weight="700">최신일 SPI6 단계 분포</text>`;
  svg += `<text x="${width / 2}" y="58" text-anchor="middle" font-family="Arial, sans-serif" font-size="13" fill="#555">2026-04-25, 66개 지점</text>`;
  order.forEach((label, i) => {
    const value = counts[label] || 0;
    const h = ((height - margin.top - margin.bottom) * value) / maxValue;
    const x = margin.left + i * (barW + gap);
    const y = height - margin.bottom - h;
    svg += `<rect x="${x}" y="${y}" width="${barW}" height="${h}" rx="4" fill="${colors[label]}"/>`;
    svg += `<text x="${x + barW / 2}" y="${y - 8}" text-anchor="middle" font-family="Arial, sans-serif" font-size="13">${value}</text>`;
    svg += `<text x="${x + barW / 2}" y="${height - 22}" text-anchor="middle" font-family="Arial, sans-serif" font-size="12">${label}</text>`;
  });
  svg += `</svg>`;
  return svg;
}

function makeReport(summaryRows) {
  const seriousTop = [...summaryRows].sort((a, b) => b.serious_total_days - a.serious_total_days).slice(0, 15);
  const interestTop = [...summaryRows].sort((a, b) => b.interest_total_days - a.interest_total_days).slice(0, 10);
  const latestDrought = summaryRows
    .filter((row) => row.latest_spi6 <= -1)
    .sort((a, b) => a.latest_spi6 - b.latest_spi6);

  const lines = [];
  lines.push("# 66개 지점별 SPI6 가뭄 지속기간 분석");
  lines.push("");
  lines.push("- 기준: 관심 SPI6<=-1.00, 주의 SPI6<=-1.50, 경계 SPI6<=-2.00, 심각 SPI6<=-2.00 20일 이상 지속");
  lines.push("- 윤일은 연속으로 처리하고, 그 외 누락일은 지속구간을 끊었습니다.");
  lines.push("");
  lines.push("## 심각 조건 누적일수 상위");
  lines.push("");
  lines.push("| 순위 | 지점 | 심각 누적일수 | 심각 구간 수 | 최장 심각 | 최악 SPI6 |");
  lines.push("|---:|---|---:|---:|---:|---:|");
  seriousTop.forEach((row, index) => {
    lines.push(`| ${index + 1} | ${row.station_code} ${row.station_name} | ${row.serious_total_days} | ${row.serious_episodes} | ${row.serious_max_days} | ${row.serious_worst_spi6} |`);
  });
  lines.push("");
  lines.push("## 관심 이상 누적일수 상위");
  lines.push("");
  lines.push("| 순위 | 지점 | 관심 이상 누적일수 | 구간 수 | 최장 관심 | 최악 SPI6 |");
  lines.push("|---:|---|---:|---:|---:|---:|");
  interestTop.forEach((row, index) => {
    lines.push(`| ${index + 1} | ${row.station_code} ${row.station_name} | ${row.interest_total_days} | ${row.interest_episodes} | ${row.interest_max_days} | ${row.interest_worst_spi6} |`);
  });
  lines.push("");
  lines.push("## 최신일 가뭄 지점");
  lines.push("");
  lines.push("| 지점 | SPI6 | 단계 |");
  lines.push("|---|---:|---|");
  latestDrought.forEach((row) => {
    lines.push(`| ${row.station_code} ${row.station_name} | ${row.latest_spi6} | ${row.latest_stage} |`);
  });
  lines.push("");
  lines.push("## 산출 파일");
  lines.push("");
  lines.push("- `spi6_station_summary.csv`: 66개 지점별 SPI6 지속기간 요약");
  lines.push("- `spi6_episodes.csv`: SPI6 지속구간 전체 목록");
  lines.push("- `spi6_station_heatmap.svg`, `spi6_serious_top20.svg`, `spi6_interest_top20.svg`, `spi6_latest_stage.svg`: 그래픽 요약");
  return lines.join("\n") + "\n";
}

function main() {
  fs.mkdirSync(outDir, { recursive: true });
  const rows = readRows();
  const { summaryRows, allEpisodes } = buildStationSummary(rows);

  writeCsv(path.join(outDir, "spi6_station_summary.csv"), summaryRows, [
    "station_code",
    "station_name",
    "first_date",
    "last_date",
    "data_days",
    "latest_spi6",
    "latest_stage",
    "worst_spi6",
    "interest_episodes",
    "interest_total_days",
    "interest_max_days",
    "interest_max_period",
    "interest_worst_spi6",
    "caution_episodes",
    "caution_total_days",
    "caution_max_days",
    "caution_max_period",
    "caution_worst_spi6",
    "alert_episodes",
    "alert_total_days",
    "alert_max_days",
    "alert_max_period",
    "alert_worst_spi6",
    "serious_episodes",
    "serious_total_days",
    "serious_max_days",
    "serious_max_period",
    "serious_worst_spi6",
  ]);
  writeCsv(path.join(outDir, "spi6_episodes.csv"), allEpisodes, [
    "level_key",
    "level_ko",
    "threshold",
    "station_code",
    "station_name",
    "start_date",
    "end_date",
    "duration",
    "min_spi6",
  ]);

  fs.writeFileSync(path.join(outDir, "spi6_station_heatmap.svg"), stationHeatmap(summaryRows), "utf8");
  fs.writeFileSync(path.join(outDir, "spi6_serious_top20.svg"), topStationBars(summaryRows, "serious", "SPI6 심각 조건 누적일수 상위 20개 지점", "SPI6<=-2.00이 20일 이상 지속된 구간의 일수 합계"), "utf8");
  fs.writeFileSync(path.join(outDir, "spi6_interest_top20.svg"), topStationBars(summaryRows, "interest", "SPI6 관심 이상 누적일수 상위 20개 지점", "SPI6<=-1.00 지속구간의 일수 합계"), "utf8");
  fs.writeFileSync(path.join(outDir, "spi6_latest_stage.svg"), latestStageChart(summaryRows), "utf8");
  fs.writeFileSync(path.join(outDir, "spi6_station_report.md"), makeReport(summaryRows), "utf8");

  const seriousTop = [...summaryRows].sort((a, b) => b.serious_total_days - a.serious_total_days).slice(0, 10);
  const latestDrought = summaryRows.filter((row) => row.latest_spi6 <= -1).length;
  console.log(`rows=${rows.length}`);
  console.log(`stations=${summaryRows.length}`);
  console.log(`episodes=${allEpisodes.length}`);
  console.log(`latest_drought_stations=${latestDrought}`);
  console.log(`outDir=${outDir}`);
  console.table(
    seriousTop.map((row) => ({
      code: row.station_code,
      name: row.station_name,
      serious_total_days: row.serious_total_days,
      serious_episodes: row.serious_episodes,
      serious_max_days: row.serious_max_days,
      worst_spi6: row.serious_worst_spi6,
    })),
  );
}

main();
