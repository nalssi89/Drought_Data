const fs = require("fs");
const path = require("path");
const { execFileSync } = require("child_process");
const { pathToFileURL } = require("url");

const defaultDirs = [
  "outputs/spi6_station_duration_analysis",
  "outputs/spi_drought_duration_analysis",
];

const chromeCandidates = [
  "C:/Program Files/Google/Chrome/Application/chrome.exe",
  "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
  "C:/Program Files/Microsoft/Edge/Application/msedge.exe",
];

function findBrowser() {
  const browser = chromeCandidates.find((candidate) => fs.existsSync(candidate));
  if (!browser) {
    throw new Error("Chrome/Edge executable was not found.");
  }
  return browser;
}

function readSvgSize(svgPath) {
  const text = fs.readFileSync(svgPath, "utf8");
  const width = Number((/width="(\d+(?:\.\d+)?)"/.exec(text) || [])[1]);
  const height = Number((/height="(\d+(?:\.\d+)?)"/.exec(text) || [])[1]);
  if (!width || !height) {
    throw new Error(`Could not read SVG size: ${svgPath}`);
  }
  return { width: Math.ceil(width), height: Math.ceil(height) };
}

function exportPng(browserPath, svgPath) {
  const { width, height } = readSvgSize(svgPath);
  const pngPath = svgPath.replace(/\.svg$/i, ".png");
  execFileSync(browserPath, [
    "--headless=new",
    "--disable-gpu",
    "--hide-scrollbars",
    "--allow-file-access-from-files",
    `--window-size=${width},${height}`,
    `--screenshot=${pngPath}`,
    pathToFileURL(path.resolve(svgPath)).href,
  ], { stdio: "ignore" });
  return pngPath;
}

function main() {
  const dirs = process.argv.slice(2);
  const targetDirs = dirs.length ? dirs : defaultDirs;
  const browserPath = findBrowser();
  const exported = [];

  for (const dir of targetDirs) {
    const absoluteDir = path.resolve(dir);
    if (!fs.existsSync(absoluteDir)) continue;
    for (const name of fs.readdirSync(absoluteDir)) {
      if (!name.toLowerCase().endsWith(".svg")) continue;
      exported.push(exportPng(browserPath, path.join(absoluteDir, name)));
    }
  }

  console.log(`browser=${browserPath}`);
  console.log(`exported=${exported.length}`);
  for (const file of exported) console.log(file);
}

main();
