const fs = require("fs");
const path = require("path");

const inDir = path.resolve("outputs/spi6_station_duration_analysis");
const episodePath = path.join(inDir, "spi6_episodes.csv");
const outDir = inDir;

const levels = [
  { key: "interest", ko: "관심이상", color: "#f59e0b" },
  { key: "caution", ko: "주의이상", color: "#ef4444" },
  { key: "alert", ko: "경계이상", color: "#991b1b" },
  { key: "serious", ko: "심각이상", color: "#4c0519" },
];

function readCsv(filePath) {
  const text = fs.readFileSync(filePath, "utf8").replace(/^\uFEFF/, "");
  const lines = text.trim().split(/\r?\n/);
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

function yearsTouched(startDate, endDate) {
  const start = Number(startDate.slice(0, 4));
  const end = Number(endDate.slice(0, 4));
  const years = [];
  for (let year = start; year <= end; year += 1) years.push(year);
  return years;
}

function dayNumber(dateText) {
  const [year, month, day] = dateText.split("-").map(Number);
  return Date.UTC(year, month - 1, day) / 86400000;
}

function overlapDaysInYear(startDate, endDate, year) {
  const start = Math.max(dayNumber(startDate), dayNumber(`${year}-01-01`));
  const end = Math.min(dayNumber(endDate), dayNumber(`${year}-12-31`));
  return Math.max(0, end - start + 1);
}

function svgHeader(width, height) {
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}">`;
}

function lineChart(rows, years) {
  const width = 1160;
  const height = 660;
  const margin = { top: 76, right: 170, bottom: 112, left: 70 };
  const plotWidth = width - margin.left - margin.right;
  const plotHeight = height - margin.top - margin.bottom;
  const maxValue = Math.max(...rows.map((row) => Number(row.station_count)), 1);
  const byLevel = new Map(levels.map((level) => [level.key, rows.filter((row) => row.level_key === level.key)]));

  function x(year) {
    return margin.left + ((year - years[0]) / (years[years.length - 1] - years[0])) * plotWidth;
  }
  function y(value) {
    return margin.top + plotHeight - (value / maxValue) * plotHeight;
  }

  let svg = svgHeader(width, height);
  svg += `<rect width="100%" height="100%" fill="#ffffff"/>`;
  svg += `<text x="${width / 2}" y="34" text-anchor="middle" font-family="Arial, sans-serif" font-size="23" font-weight="700">SPI6 2개월 이상 지속구간 연도별 발생 지점 수</text>`;
  svg += `<text x="${width / 2}" y="58" text-anchor="middle" font-family="Arial, sans-serif" font-size="13" fill="#555">해당 연도에 60일 이상 지속구간이 걸친 지점 수. 한 구간이 여러 해에 걸치면 각 연도에 포함</text>`;

  for (let i = 0; i <= 6; i += 1) {
    const value = Math.round((maxValue * i) / 6);
    const yy = y(value);
    svg += `<line x1="${margin.left}" y1="${yy}" x2="${width - margin.right}" y2="${yy}" stroke="#e5e7eb"/>`;
    svg += `<text x="${margin.left - 10}" y="${yy + 4}" text-anchor="end" font-family="Arial, sans-serif" font-size="11" fill="#555">${value}</text>`;
  }
  years.forEach((year, i) => {
    if (i % 2 !== 0) return;
    const xx = x(year);
    svg += `<line x1="${xx}" y1="${margin.top + plotHeight}" x2="${xx}" y2="${margin.top + plotHeight + 6}" stroke="#111"/>`;
    svg += `<text x="${xx}" y="${margin.top + plotHeight - 10}" text-anchor="middle" font-family="Arial, sans-serif" font-size="12" font-weight="700" fill="#111">${year}</text>`;
  });

  levels.forEach((level, idx) => {
    const series = byLevel.get(level.key);
    const points = series.map((row) => `${x(Number(row.year)).toFixed(1)},${y(Number(row.station_count)).toFixed(1)}`).join(" ");
    svg += `<polyline points="${points}" fill="none" stroke="${level.color}" stroke-width="3"/>`;
    for (const row of series) {
      const value = Number(row.station_count);
      if (!value) continue;
      svg += `<circle cx="${x(Number(row.year))}" cy="${y(value)}" r="3.5" fill="${level.color}"/>`;
    }
    const legendY = margin.top + idx * 24;
    svg += `<rect x="${width - margin.right + 28}" y="${legendY - 11}" width="14" height="14" fill="${level.color}"/>`;
    svg += `<text x="${width - margin.right + 50}" y="${legendY + 1}" font-family="Arial, sans-serif" font-size="13">${level.ko}</text>`;
  });
  svg += `<line x1="${margin.left}" y1="${margin.top + plotHeight}" x2="${width - margin.right}" y2="${margin.top + plotHeight}" stroke="#111"/>`;
  svg += `<text x="${width / 2}" y="${height - 18}" text-anchor="middle" font-family="Arial, sans-serif" font-size="12" fill="#666">단위: 지점 수(최대 66). 2001~2026 자료 기준</text>`;
  svg += `</svg>`;
  return svg;
}

function heatmap(rows, years) {
  const width = 1180;
  const height = 420;
  const margin = { top: 86, right: 40, bottom: 50, left: 95 };
  const cellW = (width - margin.left - margin.right) / years.length;
  const cellH = 48;
  const maxValue = Math.max(...rows.map((row) => Number(row.station_count)), 1);

  let svg = svgHeader(width, height);
  svg += `<rect width="100%" height="100%" fill="#ffffff"/>`;
  svg += `<text x="${width / 2}" y="34" text-anchor="middle" font-family="Arial, sans-serif" font-size="23" font-weight="700">연도별 SPI6 2개월 이상 발생 빈도 히트맵</text>`;
  svg += `<text x="${width / 2}" y="58" text-anchor="middle" font-family="Arial, sans-serif" font-size="13" fill="#555">색이 진할수록 해당 계급의 60일 이상 지속구간을 경험한 지점 수가 많음</text>`;
  levels.forEach((level, r) => {
    const y = margin.top + r * (cellH + 8);
    svg += `<text x="${margin.left - 12}" y="${y + cellH * 0.62}" text-anchor="end" font-family="Arial, sans-serif" font-size="13" font-weight="700">${level.ko}</text>`;
    years.forEach((year, c) => {
      const row = rows.find((item) => item.level_key === level.key && Number(item.year) === year);
      const value = row ? Number(row.station_count) : 0;
      const alpha = value ? 0.12 + 0.78 * (value / maxValue) : 0.03;
      const x = margin.left + c * cellW;
      svg += `<rect x="${x}" y="${y}" width="${cellW - 2}" height="${cellH}" fill="rgba(220,38,38,${alpha.toFixed(3)})" stroke="#fff"/>`;
      if (value) {
        svg += `<text x="${x + cellW / 2}" y="${y + cellH * 0.62}" text-anchor="middle" font-family="Arial, sans-serif" font-size="11" fill="${alpha > 0.5 ? "#fff" : "#111"}">${value}</text>`;
      }
    });
  });
  years.forEach((year, i) => {
    if (i % 2 !== 0) return;
    const x = margin.left + i * cellW + cellW / 2;
    svg += `<text x="${x}" y="${margin.top - 10}" text-anchor="middle" font-family="Arial, sans-serif" font-size="10" font-weight="700" fill="#111">${year}</text>`;
  });
  svg += `</svg>`;
  return svg;
}

function topStationYearSvg(rows) {
  const selected = rows
    .filter((row) => row.total_60day_episode_count > 0)
    .sort((a, b) => b.total_60day_episode_count - a.total_60day_episode_count || b.total_overlap_days - a.total_overlap_days)
    .slice(0, 24);
  const width = 1120;
  const height = 760;
  const margin = { top: 76, right: 135, bottom: 44, left: 170 };
  const barH = 20;
  const gap = 6;
  const maxValue = Math.max(...selected.map((row) => row.total_60day_episode_count), 1);

  let svg = svgHeader(width, height);
  svg += `<rect width="100%" height="100%" fill="#ffffff"/>`;
  svg += `<text x="${width / 2}" y="34" text-anchor="middle" font-family="Arial, sans-serif" font-size="23" font-weight="700">지점-연도별 2개월 이상 지속구간 빈도 상위</text>`;
  svg += `<text x="${width / 2}" y="58" text-anchor="middle" font-family="Arial, sans-serif" font-size="13" fill="#555">관심/주의/경계/심각 계급의 60일 이상 구간 수 합계 기준</text>`;
  selected.forEach((row, i) => {
    const y = margin.top + i * (barH + gap);
    const value = Number(row.total_60day_episode_count);
    const w = ((width - margin.left - margin.right) * value) / maxValue;
    svg += `<text x="${margin.left - 10}" y="${y + 15}" text-anchor="end" font-family="Arial, sans-serif" font-size="12">${row.year} ${row.station_code} ${row.station_name}</text>`;
    svg += `<rect x="${margin.left}" y="${y}" width="${w}" height="${barH}" rx="4" fill="#dc2626"/>`;
    svg += `<text x="${margin.left + w + 8}" y="${y + 15}" font-family="Arial, sans-serif" font-size="12">${value}건 / ${row.total_overlap_days}일</text>`;
  });
  svg += `</svg>`;
  return svg;
}

function main() {
  const episodes = readCsv(episodePath).filter((episode) => Number(episode.duration) >= 60);
  const years = [];
  for (let year = 2001; year <= 2026; year += 1) years.push(year);

  const yearlyLevelRows = [];
  const stationYear = new Map();
  for (const year of years) {
    for (const level of levels) {
      const selected = episodes.filter(
        (episode) =>
          episode.level_key === level.key &&
          Number(episode.start_date.slice(0, 4)) <= year &&
          Number(episode.end_date.slice(0, 4)) >= year,
      );
      const stationSet = new Set(selected.map((episode) => episode.station_code));
      const startCount = selected.filter((episode) => Number(episode.start_date.slice(0, 4)) === year).length;
      const overlapDays = selected.reduce((sum, episode) => sum + overlapDaysInYear(episode.start_date, episode.end_date, year), 0);
      yearlyLevelRows.push({
        year,
        level_key: level.key,
        level: level.ko,
        station_count: stationSet.size,
        episode_count: selected.length,
        episode_start_count: startCount,
        overlap_days: overlapDays,
      });

      for (const episode of selected) {
        const key = `${year}|${episode.station_code}|${episode.station_name}`;
        if (!stationYear.has(key)) {
          stationYear.set(key, {
            year,
            station_code: episode.station_code,
            station_name: episode.station_name,
            interest_episode_count: 0,
            caution_episode_count: 0,
            alert_episode_count: 0,
            serious_episode_count: 0,
            interest_overlap_days: 0,
            caution_overlap_days: 0,
            alert_overlap_days: 0,
            serious_overlap_days: 0,
          });
        }
        const row = stationYear.get(key);
        row[`${level.key}_episode_count`] += 1;
        row[`${level.key}_overlap_days`] += overlapDaysInYear(episode.start_date, episode.end_date, year);
      }
    }
  }

  const stationYearRows = [...stationYear.values()]
    .map((row) => ({
      ...row,
      total_60day_episode_count:
        row.interest_episode_count + row.caution_episode_count + row.alert_episode_count + row.serious_episode_count,
      total_overlap_days:
        row.interest_overlap_days + row.caution_overlap_days + row.alert_overlap_days + row.serious_overlap_days,
    }))
    .sort((a, b) => Number(a.year) - Number(b.year) || Number(a.station_code) - Number(b.station_code));

  writeCsv(path.join(outDir, "spi6_2month_yearly_level_frequency.csv"), yearlyLevelRows, [
    "year",
    "level_key",
    "level",
    "station_count",
    "episode_count",
    "episode_start_count",
    "overlap_days",
  ]);
  writeCsv(path.join(outDir, "spi6_2month_station_year_frequency.csv"), stationYearRows, [
    "year",
    "station_code",
    "station_name",
    "interest_episode_count",
    "interest_overlap_days",
    "caution_episode_count",
    "caution_overlap_days",
    "alert_episode_count",
    "alert_overlap_days",
    "serious_episode_count",
    "serious_overlap_days",
    "total_60day_episode_count",
    "total_overlap_days",
  ]);

  fs.writeFileSync(path.join(outDir, "spi6_2month_yearly_timeseries.svg"), lineChart(yearlyLevelRows, years), "utf8");
  fs.writeFileSync(path.join(outDir, "spi6_2month_yearly_heatmap.svg"), heatmap(yearlyLevelRows, years), "utf8");
  fs.writeFileSync(path.join(outDir, "spi6_2month_station_year_top.svg"), topStationYearSvg(stationYearRows), "utf8");

  console.log(`episodes_60day=${episodes.length}`);
  console.log(`station_year_rows=${stationYearRows.length}`);
  console.log(`outDir=${outDir}`);
  console.table(
    yearlyLevelRows
      .filter((row) => row.station_count > 0)
      .sort((a, b) => b.station_count - a.station_count || Number(a.year) - Number(b.year))
      .slice(0, 12),
  );
}

main();
