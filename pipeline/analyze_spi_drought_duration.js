const fs = require("fs");
const path = require("path");
const { TextDecoder } = require("util");

const inputPaths = [
  "C:/Users/user/Downloads/CLM_SPI_DD_20260427163903.csv",
  "C:/Users/user/Downloads/CLM_SPI_DD_20260427164047.csv",
  "C:/Users/user/Downloads/CLM_SPI_DD_20260427171016.csv",
];

const outDir = path.resolve("outputs/spi_drought_duration_analysis");
const decoder = new TextDecoder("windows-949");

const thresholds = [
  { key: "interest", ko: "관심", value: -1.0 },
  { key: "caution", ko: "주의", value: -1.5 },
  { key: "alert", ko: "경계", value: -2.0 },
];

const seriousKey = "serious";
const seriousKo = "심각";
const indexes = ["SPI3", "SPI6"];

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

function isLeapDay(dateText) {
  return dateText.slice(5) === "02-29";
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
  const lines = [
    columns.join(","),
    ...rows.map((row) => columns.map((col) => csvEscape(row[col])).join(",")),
  ];
  fs.writeFileSync(filePath, lines.join("\n") + "\n", "utf8");
}

function percentile(values, p) {
  if (!values.length) return "";
  const sorted = [...values].sort((a, b) => a - b);
  const idx = (sorted.length - 1) * p;
  const lo = Math.floor(idx);
  const hi = Math.ceil(idx);
  if (lo === hi) return sorted[lo];
  return sorted[lo] + (sorted[hi] - sorted[lo]) * (idx - lo);
}

function round(value, digits = 1) {
  if (value === "") return "";
  return Number(value).toFixed(digits).replace(/\.0$/, "");
}

function summarizeEpisodes(episodes) {
  const durations = episodes.map((episode) => episode.duration);
  const totalDays = durations.reduce((sum, value) => sum + value, 0);
  const maxEpisode = [...episodes].sort((a, b) => b.duration - a.duration)[0];
  return {
    episode_count: episodes.length,
    station_count: new Set(episodes.map((episode) => episode.station_code)).size,
    total_days: totalDays,
    mean_days: durations.length ? totalDays / durations.length : "",
    median_days: percentile(durations, 0.5),
    p90_days: percentile(durations, 0.9),
    max_days: durations.length ? Math.max(...durations) : "",
    max_station: maxEpisode ? `${maxEpisode.station_code} ${maxEpisode.station_name}` : "",
    max_start: maxEpisode ? maxEpisode.start_date : "",
    max_end: maxEpisode ? maxEpisode.end_date : "",
  };
}

function readRows() {
  const rows = [];
  for (const inputPath of inputPaths) {
    const text = decoder.decode(fs.readFileSync(inputPath));
    const lines = text.trimEnd().split(/\r?\n/);
    for (const line of lines.slice(1)) {
      if (!line.trim()) continue;
      const [stationCode, stationName, date, spi3, spi6] = line.split(",").map((value) => value.trim());
      rows.push({
        station_code: stationCode,
        station_name: stationName,
        date,
        SPI3: parseNumber(spi3),
        SPI6: parseNumber(spi6),
      });
    }
  }
  return rows;
}

function buildEpisodes(rows) {
  const grouped = new Map();
  for (const row of rows) {
    const stationKey = `${row.station_code}|${row.station_name}`;
    if (!grouped.has(stationKey)) grouped.set(stationKey, []);
    grouped.get(stationKey).push(row);
  }

  const episodes = [];
  for (const [stationKey, stationRows] of grouped.entries()) {
    const [stationCode, stationName] = stationKey.split("|");
    stationRows.sort((a, b) => a.date.localeCompare(b.date));

    for (const index of indexes) {
      for (const threshold of thresholds) {
        let current = null;
        for (const row of stationRows) {
          const value = row[index];
          const active = value !== null && value <= threshold.value;
          const continuous = current && isConsecutive(current.end_date, row.date);

          if (!active || !continuous) {
            if (current) episodes.push(current);
            current = null;
          }

          if (active) {
            if (!current) {
              current = {
                index,
                level_key: threshold.key,
                level_ko: threshold.ko,
                threshold: threshold.value,
                station_code: stationCode,
                station_name: stationName,
                start_date: row.date,
                end_date: row.date,
                duration: 1,
                min_spi: value,
              };
            } else {
              current.end_date = row.date;
              current.duration += 1;
              current.min_spi = Math.min(current.min_spi, value);
            }
          }
        }
        if (current) episodes.push(current);
      }
    }
  }

  const seriousEpisodes = episodes
    .filter((episode) => episode.level_key === "alert" && episode.duration >= 20)
    .map((episode) => ({
      ...episode,
      level_key: seriousKey,
      level_ko: seriousKo,
    }));

  return [...episodes, ...seriousEpisodes];
}

function buildSummaries(episodes) {
  const thresholdSummary = [];
  for (const index of indexes) {
    for (const level of [...thresholds, { key: seriousKey, ko: seriousKo }]) {
      const selected = episodes.filter((episode) => episode.index === index && episode.level_key === level.key);
      const summary = summarizeEpisodes(selected);
      thresholdSummary.push({
        index,
        level: level.ko,
        threshold_definition:
          level.key === seriousKey ? "SPI <= -2.00 for >=20 consecutive days" : `SPI <= ${level.value.toFixed(2)}`,
        ...Object.fromEntries(
          Object.entries(summary).map(([key, value]) => [
            key,
            typeof value === "number" && !Number.isInteger(value) ? round(value, 1) : value,
          ]),
        ),
      });
    }
  }

  const stationRows = [];
  for (const index of indexes) {
    for (const level of [...thresholds, { key: seriousKey, ko: seriousKo }]) {
      const byStation = new Map();
      for (const episode of episodes.filter((item) => item.index === index && item.level_key === level.key)) {
        const key = `${episode.station_code}|${episode.station_name}`;
        if (!byStation.has(key)) {
          byStation.set(key, {
            index,
            level: level.ko,
            station_code: episode.station_code,
            station_name: episode.station_name,
            episode_count: 0,
            total_days: 0,
            max_days: 0,
            worst_spi: "",
          });
        }
        const row = byStation.get(key);
        row.episode_count += 1;
        row.total_days += episode.duration;
        row.max_days = Math.max(row.max_days, episode.duration);
        row.worst_spi = row.worst_spi === "" ? episode.min_spi : Math.min(row.worst_spi, episode.min_spi);
      }
      stationRows.push(...byStation.values());
    }
  }

  stationRows.sort((a, b) =>
    a.index.localeCompare(b.index) ||
    a.level.localeCompare(b.level, "ko") ||
    b.total_days - a.total_days ||
    Number(a.station_code) - Number(b.station_code),
  );

  return { thresholdSummary, stationRows };
}

function svgHeader(width, height) {
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}">`;
}

function durationBarSvg(summaryRows) {
  const width = 980;
  const height = 560;
  const margin = { top: 70, right: 40, bottom: 70, left: 90 };
  const plotWidth = width - margin.left - margin.right;
  const plotHeight = height - margin.top - margin.bottom;
  const rows = summaryRows.filter((row) => row.level !== "심각");
  const maxValue = Math.max(...rows.map((row) => Number(row.total_days)));
  const barGap = 16;
  const groupGap = 30;
  const barHeight = (plotHeight - groupGap) / 6 - barGap;
  const colors = { SPI3: "#3b82f6", SPI6: "#ef4444" };

  let svg = svgHeader(width, height);
  svg += `<rect width="100%" height="100%" fill="#ffffff"/>`;
  svg += `<text x="${width / 2}" y="34" text-anchor="middle" font-family="Arial, sans-serif" font-size="22" font-weight="700">SPI 가뭄단계별 누적 지속일수</text>`;
  svg += `<text x="${width / 2}" y="58" text-anchor="middle" font-family="Arial, sans-serif" font-size="13" fill="#555">지점별 지속구간 일수 합계, 단계는 임계값 이하 기준</text>`;
  for (let i = 0; i <= 5; i++) {
    const x = margin.left + (plotWidth * i) / 5;
    const value = Math.round((maxValue * i) / 5);
    svg += `<line x1="${x}" y1="${margin.top}" x2="${x}" y2="${height - margin.bottom}" stroke="#e5e7eb"/>`;
    svg += `<text x="${x}" y="${height - 42}" text-anchor="middle" font-family="Arial, sans-serif" font-size="11" fill="#555">${value.toLocaleString()}</text>`;
  }

  rows.forEach((row, i) => {
    const group = Math.floor(i / 2);
    const within = i % 2;
    const y = margin.top + group * (barHeight * 2 + barGap + groupGap) + within * (barHeight + barGap);
    const value = Number(row.total_days);
    const w = (value / maxValue) * plotWidth;
    svg += `<text x="${margin.left - 12}" y="${y + barHeight * 0.65}" text-anchor="end" font-family="Arial, sans-serif" font-size="13">${row.level} ${row.index}</text>`;
    svg += `<rect x="${margin.left}" y="${y}" width="${w}" height="${barHeight}" rx="4" fill="${colors[row.index]}"/>`;
    svg += `<text x="${margin.left + w + 8}" y="${y + barHeight * 0.65}" font-family="Arial, sans-serif" font-size="12" fill="#111">${value.toLocaleString()}일</text>`;
  });
  svg += `<text x="${width / 2}" y="${height - 14}" text-anchor="middle" font-family="Arial, sans-serif" font-size="12" fill="#666">관심: SPI<=-1.00, 주의: SPI<=-1.50, 경계: SPI<=-2.00</text>`;
  svg += `</svg>`;
  return svg;
}

function durationDistributionSvg(summaryRows) {
  const width = 1020;
  const height = 610;
  const margin = { top: 74, right: 90, bottom: 58, left: 130 };
  const plotWidth = width - margin.left - margin.right;
  const rowHeight = 44;
  const rows = summaryRows;
  const maxValue = Math.max(...rows.map((row) => Number(row.max_days)));
  const colors = { SPI3: "#2563eb", SPI6: "#dc2626" };

  let svg = svgHeader(width, height);
  svg += `<rect width="100%" height="100%" fill="#ffffff"/>`;
  svg += `<text x="${width / 2}" y="34" text-anchor="middle" font-family="Arial, sans-serif" font-size="22" font-weight="700">가뭄 지속구간 기간분포</text>`;
  svg += `<text x="${width / 2}" y="58" text-anchor="middle" font-family="Arial, sans-serif" font-size="13" fill="#555">막대=최장, 굵은 점=90퍼센타일, 흰 점=중앙값</text>`;

  for (let i = 0; i <= 6; i++) {
    const value = Math.round((maxValue * i) / 6);
    const x = margin.left + (plotWidth * value) / maxValue;
    svg += `<line x1="${x}" y1="${margin.top - 12}" x2="${x}" y2="${margin.top + rows.length * rowHeight - 10}" stroke="#e5e7eb"/>`;
    svg += `<text x="${x}" y="${height - 24}" text-anchor="middle" font-family="Arial, sans-serif" font-size="11" fill="#555">${value}</text>`;
  }

  rows.forEach((row, i) => {
    const y = margin.top + i * rowHeight;
    const maxDays = Number(row.max_days);
    const p90 = Number(row.p90_days);
    const median = Number(row.median_days);
    const xMax = margin.left + (plotWidth * maxDays) / maxValue;
    const xP90 = margin.left + (plotWidth * p90) / maxValue;
    const xMedian = margin.left + (plotWidth * median) / maxValue;
    svg += `<text x="${margin.left - 12}" y="${y + 18}" text-anchor="end" font-family="Arial, sans-serif" font-size="13">${row.index} ${row.level}</text>`;
    svg += `<line x1="${margin.left}" y1="${y + 12}" x2="${xMax}" y2="${y + 12}" stroke="${colors[row.index]}" stroke-width="12" stroke-linecap="round" opacity="0.28"/>`;
    svg += `<circle cx="${xP90}" cy="${y + 12}" r="6" fill="${colors[row.index]}"/>`;
    svg += `<circle cx="${xMedian}" cy="${y + 12}" r="5" fill="#fff" stroke="${colors[row.index]}" stroke-width="2"/>`;
    svg += `<text x="${xMax + 7}" y="${y + 17}" font-family="Arial, sans-serif" font-size="12" fill="#111">최장 ${maxDays}일</text>`;
  });
  svg += `<text x="${width / 2}" y="${height - 8}" text-anchor="middle" font-family="Arial, sans-serif" font-size="12" fill="#666">일 단위. 심각은 SPI<=-2.00이 20일 이상 지속된 구간만 포함</text>`;
  svg += `</svg>`;
  return svg;
}

function topEpisodesSvg(episodes) {
  const selected = episodes
    .filter((episode) => episode.level_key === seriousKey)
    .sort((a, b) => b.duration - a.duration)
    .slice(0, 15);
  const width = 1080;
  const height = 600;
  const margin = { top: 70, right: 110, bottom: 40, left: 210 };
  const plotWidth = width - margin.left - margin.right;
  const barHeight = 24;
  const gap = 8;
  const maxValue = Math.max(...selected.map((row) => row.duration), 1);
  const colors = { SPI3: "#2563eb", SPI6: "#dc2626" };

  let svg = svgHeader(width, height);
  svg += `<rect width="100%" height="100%" fill="#ffffff"/>`;
  svg += `<text x="${width / 2}" y="34" text-anchor="middle" font-family="Arial, sans-serif" font-size="22" font-weight="700">심각 조건 지속구간 상위 15건</text>`;
  svg += `<text x="${width / 2}" y="58" text-anchor="middle" font-family="Arial, sans-serif" font-size="13" fill="#555">SPI<=-2.00이 20일 이상 연속된 구간</text>`;
  selected.forEach((row, i) => {
    const y = margin.top + i * (barHeight + gap);
    const label = `${row.index} ${row.station_name} ${row.start_date}~${row.end_date}`;
    const w = (row.duration / maxValue) * plotWidth;
    svg += `<text x="${margin.left - 10}" y="${y + 17}" text-anchor="end" font-family="Arial, sans-serif" font-size="12">${label}</text>`;
    svg += `<rect x="${margin.left}" y="${y}" width="${w}" height="${barHeight}" rx="4" fill="${colors[row.index]}"/>`;
    svg += `<text x="${margin.left + w + 8}" y="${y + 17}" font-family="Arial, sans-serif" font-size="12">${row.duration}일 / 최저 ${row.min_spi}</text>`;
  });
  svg += `</svg>`;
  return svg;
}

function stationHeatmapSvg(stationRows) {
  const selected = stationRows.filter((row) => row.level === "심각");
  const stationTotals = new Map();
  for (const row of selected) {
    const key = `${row.station_code}|${row.station_name}`;
    if (!stationTotals.has(key)) stationTotals.set(key, { station_code: row.station_code, station_name: row.station_name, SPI3: 0, SPI6: 0 });
    stationTotals.get(key)[row.index] += row.total_days;
  }
  const rows = [...stationTotals.values()]
    .filter((row) => row.SPI3 || row.SPI6)
    .sort((a, b) => b.SPI3 + b.SPI6 - (a.SPI3 + a.SPI6))
    .slice(0, 25);
  const width = 860;
  const height = 760;
  const margin = { top: 80, right: 70, bottom: 50, left: 120 };
  const cellW = 230;
  const cellH = 24;
  const maxValue = Math.max(...rows.flatMap((row) => [row.SPI3, row.SPI6]), 1);

  let svg = svgHeader(width, height);
  svg += `<rect width="100%" height="100%" fill="#ffffff"/>`;
  svg += `<text x="${width / 2}" y="34" text-anchor="middle" font-family="Arial, sans-serif" font-size="22" font-weight="700">지점별 심각 조건 누적일수 상위</text>`;
  svg += `<text x="${width / 2}" y="58" text-anchor="middle" font-family="Arial, sans-serif" font-size="13" fill="#555">SPI<=-2.00이 20일 이상 지속된 구간의 일수 합계</text>`;
  svg += `<text x="${margin.left + cellW / 2}" y="${margin.top - 14}" text-anchor="middle" font-family="Arial, sans-serif" font-size="13" font-weight="700">SPI3</text>`;
  svg += `<text x="${margin.left + cellW + 28 + cellW / 2}" y="${margin.top - 14}" text-anchor="middle" font-family="Arial, sans-serif" font-size="13" font-weight="700">SPI6</text>`;
  rows.forEach((row, i) => {
    const y = margin.top + i * (cellH + 2);
    svg += `<text x="${margin.left - 10}" y="${y + 17}" text-anchor="end" font-family="Arial, sans-serif" font-size="12">${row.station_code} ${row.station_name}</text>`;
    ["SPI3", "SPI6"].forEach((index, j) => {
      const x = margin.left + j * (cellW + 28);
      const value = row[index];
      const alpha = 0.12 + 0.78 * (value / maxValue);
      svg += `<rect x="${x}" y="${y}" width="${cellW}" height="${cellH}" fill="rgba(220,38,38,${alpha.toFixed(3)})" stroke="#fff"/>`;
      svg += `<text x="${x + cellW / 2}" y="${y + 17}" text-anchor="middle" font-family="Arial, sans-serif" font-size="12" fill="${alpha > 0.55 ? "#fff" : "#111"}">${value ? `${value}일` : ""}</text>`;
    });
  });
  svg += `</svg>`;
  return svg;
}

function makeReport(thresholdSummary, stationRows, episodes) {
  const lines = [];
  lines.push("# SPI3/SPI6 가뭄 지속기간 분석");
  lines.push("");
  lines.push("- 분석 자료: 2001-01-01~2026-04-25, 66개 지점(2001~2017 제공 59개, 2018년 이후 66개)");
  lines.push("- 연속성 처리: 2월 29일은 제공 체계상 제외일로 보고 연속으로 처리, 그 외 누락 날짜는 지속구간을 끊음");
  lines.push("- 단계 정의: 관심 SPI<=-1.00, 주의 SPI<=-1.50, 경계 SPI<=-2.00, 심각 SPI<=-2.00 20일 이상 지속");
  lines.push("");
  lines.push("## 단계별 지속기간 통계");
  lines.push("");
  lines.push("| 지수 | 단계 | 구간 수 | 지점 수 | 누적일수 | 평균 | 중앙값 | 90퍼센타일 | 최장 | 최장 지점/기간 |");
  lines.push("|---|---:|---:|---:|---:|---:|---:|---:|---:|---|");
  for (const row of thresholdSummary) {
    lines.push(
      `| ${row.index} | ${row.level} | ${Number(row.episode_count).toLocaleString()} | ${row.station_count} | ${Number(row.total_days).toLocaleString()} | ${row.mean_days} | ${row.median_days} | ${row.p90_days} | ${row.max_days} | ${row.max_station} ${row.max_start}~${row.max_end} |`,
    );
  }
  lines.push("");
  lines.push("## 심각 조건 상위 지속구간");
  lines.push("");
  lines.push("| 순위 | 지수 | 지점 | 시작 | 종료 | 지속일수 | 최저 SPI |");
  lines.push("|---:|---|---|---|---|---:|---:|");
  episodes
    .filter((episode) => episode.level_key === seriousKey)
    .sort((a, b) => b.duration - a.duration)
    .slice(0, 20)
    .forEach((episode, index) => {
      lines.push(
        `| ${index + 1} | ${episode.index} | ${episode.station_code} ${episode.station_name} | ${episode.start_date} | ${episode.end_date} | ${episode.duration} | ${episode.min_spi} |`,
      );
    });
  lines.push("");
  lines.push("## 산출 파일");
  lines.push("");
  lines.push("- `threshold_summary.csv`: 지수/단계별 지속기간 통계");
  lines.push("- `station_level_summary.csv`: 지점별 단계 지속일수 및 최장 지속기간");
  lines.push("- `drought_episodes.csv`: 모든 지속구간 목록");
  lines.push("- `duration_totals.svg`, `duration_distribution.svg`, `serious_top_episodes.svg`, `serious_station_heatmap.svg`: 그래픽 요약");
  return lines.join("\n") + "\n";
}

function main() {
  fs.mkdirSync(outDir, { recursive: true });
  const rows = readRows();
  const episodes = buildEpisodes(rows);
  const { thresholdSummary, stationRows } = buildSummaries(episodes);

  writeCsv(path.join(outDir, "drought_episodes.csv"), episodes, [
    "index",
    "level_key",
    "level_ko",
    "threshold",
    "station_code",
    "station_name",
    "start_date",
    "end_date",
    "duration",
    "min_spi",
  ]);
  writeCsv(path.join(outDir, "threshold_summary.csv"), thresholdSummary, [
    "index",
    "level",
    "threshold_definition",
    "episode_count",
    "station_count",
    "total_days",
    "mean_days",
    "median_days",
    "p90_days",
    "max_days",
    "max_station",
    "max_start",
    "max_end",
  ]);
  writeCsv(path.join(outDir, "station_level_summary.csv"), stationRows, [
    "index",
    "level",
    "station_code",
    "station_name",
    "episode_count",
    "total_days",
    "max_days",
    "worst_spi",
  ]);
  fs.writeFileSync(path.join(outDir, "duration_totals.svg"), durationBarSvg(thresholdSummary), "utf8");
  fs.writeFileSync(path.join(outDir, "duration_distribution.svg"), durationDistributionSvg(thresholdSummary), "utf8");
  fs.writeFileSync(path.join(outDir, "serious_top_episodes.svg"), topEpisodesSvg(episodes), "utf8");
  fs.writeFileSync(path.join(outDir, "serious_station_heatmap.svg"), stationHeatmapSvg(stationRows), "utf8");
  fs.writeFileSync(path.join(outDir, "spi_drought_duration_report.md"), makeReport(thresholdSummary, stationRows, episodes), "utf8");

  console.log(`rows=${rows.length}`);
  console.log(`episodes=${episodes.length}`);
  console.log(`outDir=${outDir}`);
  console.table(thresholdSummary);
}

main();
