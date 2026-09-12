import { readFileSync } from "node:fs";
import { buildChanAutoDrawResult } from "./chan.bundle.js";
const label = process.argv[2] || "?";
const data = JSON.parse(readFileSync(new URL("./klines.json", import.meta.url), "utf8"));
const { pens, segments } = buildChanAutoDrawResult(data);
let violations = 0, nonalt = 0, prevDir = null;
const out = [];
for (const s of segments) {
  const range = s.penIndices.map(i=>pens[i]).filter(Boolean);
  const hi = Math.max(...range.map(p=>Math.max(p.startPrice,p.endPrice)));
  const lo = Math.min(...range.map(p=>Math.min(p.startPrice,p.endPrice)));
  const dirOk = s.direction === "up" ? s.endPrice >= s.startPrice - 1e-9 : s.endPrice <= s.startPrice + 1e-9;
  const extOk = s.direction === "up" ? s.endPrice >= hi - 1e-9 : s.endPrice <= lo + 1e-9;
  const altOk = prevDir === null || prevDir !== s.direction;
  if (!dirOk || !extOk) violations++;
  if (!altOk) nonalt++;
  out.push(`  ${s.direction==="up"?"UP":"DN"} ${s.confirmed?"C":"a"}(${s.finishMode}) ${s.startPrice.toFixed(2)}->${s.endPrice.toFixed(2)} ${dirOk&&extOk?"":"!!BAD"}${altOk?"":" !!NONALT"}`);
  prevDir = s.direction;
}
console.log(`\n##### ${label}: ${segments.length} segs | dir/ext violations=${violations} nonalt=${nonalt} #####`);
console.log(out.join("\n"));
