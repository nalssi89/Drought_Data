const fs = require("fs");
const path = require("path");

const inDir = path.resolve("outputs/spi6_station_duration_analysis");
const episodePath = path.join(inDir, "spi6_episodes.csv");
const stationPath = path.join(inDir, "spi6_station_summary.csv");
const outDir = inDir;
const levels = [
  { key: "interest", ko: "관심이상", threshold: "SPI6 <= -1.00" },
  { key: "caution", ko: "주의이상", threshold: "SPI6 <= -1.50" },
  { key: "alert", ko: "경계이상", threshold: "SPI6 <= -2.00" },
  { key: "serious", ko: "심각이상", threshold: "SPI6 <= -2.00, 20일 이상 지속" },
];

function readCsv(filePath) {
  const lines = fs.readFileSync(filePath, "utf8").trim().split(/\r?\n/);
  const header = lines[0].split(",");
  return lines.slice(1).map((line) => Object.fromEntries(line.split(",").map((value, index) => [header[index], value])));
}

function csvEscape(value) {
  const text = String(value ?? "");
  return /[",\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

function writeCsv(filePath, rows, columns) {
  fs.writeFileSync(
    filePath,
    "\uFEFF" + [columns.join(","), ...rows.map((row) => columns.map((col) => csvEscape(row[col])).join(","))].join("\n") + "\n",
    "utf8",
  );
}

function svgHeader(width, height) {
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}">`;
}

function twoMonthMatrixSvg(rows) {
  const width = 1120;
  const height = 1900;
  const margin = { top: 88, right: 80, bottom: 44, left: 126 };
  const cellW = 190;
  const cellH = 23;
  const gap = 2;
  const maxValue = Math.max(...rows.flatMap((row) => levels.map((level) => Number(row[`${level.key}_max_days`]))));

  let svg = svgHeader(width, height);
  svg += `<rect width="100%" height="100%" fill="#ffffff"/>`;
  svg += `<text x="${width / 2}" y="34" text-anchor="middle" font-family="Arial, sans-serif" font-size="23" font-weight="700">SPI6 지점별 최장 연속기간과 2개월 기준</text>`;
  svg += `<text x="${width / 2}" y="60" text-anchor="middle" font-family="Arial, sans-serif" font-size="13" fill="#555">각 칸은 최장 연속일수. 굵은 테두리는 60일 이상 구간이 1회 이상 있는 지점</text>`;
  levels.forEach((level, i) => {
    const x = margin.left + i * (cellW + 18);
    svg += `<text x="${x + cellW / 2}" y="${margin.top - 16}" text-anchor="middle" font-family="Arial, sans-serif" font-size="13" font-weight="700">${level.ko}</text>`;
  });

  rows.forEach((row, r) => {
    const y = margin.top + r * (cellH + gap);
    svg += `<text x="${margin.left - 10}" y="${y + 16}" text-anchor="end" font-family="Arial, sans-serif" font-size="12">${row.station_code} ${row.station_name}</text>`;
    levels.forEach((level, c) => {
      const x = margin.left + c * (cellW + 18);
      const maxDays = Number(row[`${level.key}_max_days`]);
      const ge60 = Number(row[`${level.key}_ge60_episode_count`]);
      const alpha = maxDays ? 0.10 + 0.78 * (maxDays / maxValue) : 0.03;
      svg += `<rect x="${x}" y="${y}" width="${cellW}" height="${cellH}" fill="rgba(220,38,38,${alpha.toFixed(3)})" stroke="${ge60 ? "#111827" : "#fff"}" stroke-width="${ge60 ? 1.6 : 1}"/>`;
      svg += `<text x="${x + cellW / 2}" y="${y + 16}" text-anchor="middle" font-family="Arial, sans-serif" font-size="11" fill="${alpha > 0.52 ? "#fff" : "#111"}">${maxDays ? `${maxDays}일${ge60 ? ` (${ge60})` : ""}` : ""}</text>`;
    });
  });

  svg += `<text x="${width / 2}" y="${height - 14}" text-anchor="middle" font-family="Arial, sans-serif" font-size="12" fill="#666">괄호 안 숫자는 60일 이상 지속구간 개수</text>`;
  svg += `</svg>`;
  return svg;
}

function frequencySvg(rows) {
  const width = 880;
  const height = 430;
  const margin = { top: 78, right: 50, bottom: 58, left: 82 };
  const plotHeight = height - margin.top - margin.bottom;
  const barW = 76;
  const gap = 56;
  const maxValue = 66;

  let svg = svgHeader(width, height);
  svg += `<rect width="100%" height="100%" fill="#ffffff"/>`;
  svg += `<text x="${width / 2}" y="34" text-anchor="middle" font-family="Arial, sans-serif" font-size="23" font-weight="700">2개월 이상 지속이 나타난 지점 수</text>`;
  svg += `<text x="${width / 2}" y="58" text-anchor="middle" font-family="Arial, sans-serif" font-size="13" fill="#555">66개 지점 중 60일 이상 지속구간이 1회 이상 있는 지점</text>`;

  levels.forEach((level, i) => {
    const value = rows.filter((row) => Number(row[`${level.key}_ge60_episode_count`]) > 0).length;
    const x = margin.left + i * (barW + gap);
    const h = (plotHeight * value) / maxValue;
    const y = height - margin.bottom - h;
    svg += `<rect x="${x}" y="${y}" width="${barW}" height="${h}" rx="4" fill="#dc2626"/>`;
    svg += `<text x="${x + barW / 2}" y="${Math.max(82, y - 25)}" text-anchor="middle" font-family="Arial, sans-serif" font-size="12" font-weight="700">${level.ko}</text>`;
    svg += `<text x="${x + barW / 2}" y="${Math.max(98, y - 8)}" text-anchor="middle" font-family="Arial, sans-serif" font-size="14" font-weight="700">${value}/66</text>`;
  });
  svg += `</svg>`;
  return svg;
}

function main() {
  const episodes = readCsv(episodePath);
  const stations = readCsv(stationPath);
  const stationRows = stations.map((station) => {
    const row = {
      station_code: station.station_code,
      station_name: station.station_name,
      latest_spi6: station.latest_spi6,
      latest_stage: station.latest_stage,
    };
    for (const level of levels) {
      const selected = episodes.filter((episode) => episode.level_key === level.key && episode.station_code === station.station_code);
      const ge60 = selected.filter((episode) => Number(episode.duration) >= 60);
      const maxEpisode = [...selected].sort((a, b) => Number(b.duration) - Number(a.duration))[0];
      row[`${level.key}_episode_count`] = selected.length;
      row[`${level.key}_max_days`] = maxEpisode ? Number(maxEpisode.duration) : 0;
      row[`${level.key}_max_period`] = maxEpisode ? `${maxEpisode.start_date}~${maxEpisode.end_date}` : "";
      row[`${level.key}_ge60_episode_count`] = ge60.length;
      row[`${level.key}_ge60_total_days`] = ge60.reduce((sum, episode) => sum + Number(episode.duration), 0);
      row[`${level.key}_ge60_periods`] = ge60.map((episode) => `${episode.start_date}~${episode.end_date}(${episode.duration})`).join("|");
    }
    return row;
  });

  const longEpisodes = episodes
    .filter((episode) => Number(episode.duration) >= 60)
    .sort((a, b) => a.level_key.localeCompare(b.level_key) || Number(b.duration) - Number(a.duration));

  const frequencyRows = levels.map((level) => {
    const selected = episodes.filter((episode) => episode.level_key === level.key);
    const ge60 = selected.filter((episode) => Number(episode.duration) >= 60);
    return {
      level: level.ko,
      definition: level.threshold,
      total_episode_count: selected.length,
      ge60_episode_count: ge60.length,
      ge60_episode_pct: (ge60.length / selected.length * 100).toFixed(1),
      ge60_station_count: new Set(ge60.map((episode) => episode.station_code)).size,
      ge60_station_pct: (new Set(ge60.map((episode) => episode.station_code)).size / stationRows.length * 100).toFixed(1),
      max_days: Math.max(...selected.map((episode) => Number(episode.duration))),
    };
  });

  writeCsv(path.join(outDir, "spi6_station_continuous_periods_60day.csv"), stationRows, [
    "station_code",
    "station_name",
    "latest_spi6",
    "latest_stage",
    ...levels.flatMap((level) => [
      `${level.key}_episode_count`,
      `${level.key}_max_days`,
      `${level.key}_max_period`,
      `${level.key}_ge60_episode_count`,
      `${level.key}_ge60_total_days`,
      `${level.key}_ge60_periods`,
    ]),
  ]);
  writeCsv(path.join(outDir, "spi6_60day_episodes.csv"), longEpisodes, [
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
  writeCsv(path.join(outDir, "spi6_2month_frequency_summary.csv"), frequencyRows, [
    "level",
    "definition",
    "total_episode_count",
    "ge60_episode_count",
    "ge60_episode_pct",
    "ge60_station_count",
    "ge60_station_pct",
    "max_days",
  ]);
  fs.writeFileSync(path.join(outDir, "spi6_2month_station_matrix.svg"), twoMonthMatrixSvg(stationRows), "utf8");
  fs.writeFileSync(path.join(outDir, "spi6_2month_frequency.svg"), frequencySvg(stationRows), "utf8");

  console.table(frequencyRows);
  console.log(`outDir=${outDir}`);
}

main();
