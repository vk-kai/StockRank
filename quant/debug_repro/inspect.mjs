import { readFileSync, writeFileSync } from "node:fs";
import { buildChanAutoDrawResult } from "./chan.bundle.js";
const data = JSON.parse(readFileSync(new URL("./klines.json", import.meta.url), "utf8"));
const { pens, segments } = buildChanAutoDrawResult(data);
writeFileSync(new URL("./pens.json", import.meta.url), JSON.stringify(pens.map(p=>({i:p.index,dir:p.direction,s:+p.startPrice.toFixed(3),e:+p.endPrice.toFixed(3)})),null,0));
// find the UP segment whose endpoint isn't the range max
for (const s of segments) {
  const range = s.penIndices.map(i=>pens[i]).filter(Boolean);
  const hi = Math.max(...range.map(p=>Math.max(p.startPrice,p.endPrice)));
  const lo = Math.min(...range.map(p=>Math.min(p.startPrice,p.endPrice)));
  const extOk = s.direction==="up" ? s.endPrice >= hi-1e-9 : s.endPrice <= lo+1e-9;
  if (!extOk) {
    console.log(`BAD seg dir=${s.direction} pens[${s.startPenIndex}->${s.endPenIndex}] start=${s.startPrice} end=${s.endPrice} rangeHi=${hi} rangeLo=${lo}`);
    console.log("  pens in range:");
    for (const p of range) console.log(`    pen#${p.index} ${p.direction} ${p.startPrice}->${p.endPrice} (hi=${Math.max(p.startPrice,p.endPrice)})`);
  }
}
