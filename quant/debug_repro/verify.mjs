import { readFileSync } from "node:fs";
import { buildChanAutoDrawResult } from "./chan.bundle.js";

const files = [
  "data/kline/000001/30min.parquet",
  "data/kline/000002/30min.parquet",
  "data/kline/000009/30min.parquet",
  "data/kline/000006/30min.parquet",
  "data/kline/000012/30min.parquet",
];
let totalViolations = 0;
for (const f of files) {
  const { execSync } = await import("node:child_process");
  try { execSync(`.venv/Scripts/python.exe debug_repro/dump_klines.py "${f}" "debug_repro/klines.json"`, { stdio: "ignore" }); } catch { console.log(f, "dump failed"); continue; }
  const data = JSON.parse(readFileSync(new URL("./klines.json", import.meta.url), "utf8"));
  const { pens, segments } = buildChanAutoDrawResult(data);
  let violations = 0;
  const lines = [];
  let prevDir = null;
  for (const s of segments) {
    const upOk = s.direction === "up" ? s.endPrice >= s.startPrice : s.endPrice <= s.startPrice;
    // endpoint must be the directional extreme of its pen range
    const endPen = pens[s.endPenIndex];
    const geo = s.direction === "up"
      ? (s.endPrice >= Math.max(...s.penIndices.map(i=>pens[i]).filter(Boolean).map(p=>Math.max(p.startPrice,p.endPrice))) - 1e-9)
      : (s.endPrice <= Math.min(...s.penIndices.map(i=>pens[i]).filter(Boolean).map(p=>Math.min(p.startPrice,p.endPrice))) + 1e-9);
    const altOk = prevDir === null || prevDir !== s.direction; // segments should alternate
    if (!upOk) violations++;
    lines.push(`${s.direction==="up"?"UP":"DN"} ${s.confirmed?"C":"a"} ${s.startPrice.toFixed(2)}->${s.endPrice.toFixed(2)} ${upOk?"":"!!DIR"} ${altOk?"":"!!NONALT"}`);
    prevDir = s.direction;
  }
  totalViolations += violations;
  console.log(`\n##### ${f}: ${segments.length} segs, ${violations} direction-violations #####`);
  console.log(lines.join("\n"));
}
console.log(`\n===== TOTAL DIRECTION VIOLATIONS: ${totalViolations} =====`);
