import { readFileSync } from "node:fs";
import { buildChanAutoDrawResult, diagnoseFractal, diagnoseSegmentEndpoint } from "./chan.bundle.js";
const data = JSON.parse(readFileSync(new URL("./klines.json", import.meta.url), "utf8"));
// pick a few bars across the dataset to probe
const probes = [data[50], data[200], data[500], data[Math.floor(data.length/2)], data[data.length-5]];
let ok = 0, fail = 0;
for (const bar of probes) {
  try {
    const f = diagnoseFractal(data, bar.timestamp, bar.time);
    const s = diagnoseSegmentEndpoint(data, bar.timestamp, bar.time);
    if (f && s && typeof f.explanation === "string" && typeof s.explanation === "string") ok++;
    else fail++;
  } catch (e) { fail++; console.log("THREW on", bar.time, e.message); }
}
console.log(`diagnose smoke: ok=${ok} fail=${fail} (probed ${probes.length} bars)`);
// Also confirm result still has lines with the expected shape
const r = buildChanAutoDrawResult(data);
const bad = r.lines.filter(l => l.kind==="segment" && (l.startTimestamp>=l.endTimestamp || (l.direction==="up"? l.endPrice<l.startPrice : l.endPrice>l.startPrice)));
console.log(`lines: pens=${r.lines.filter(l=>l.kind==="pen").length} segs=${r.lines.filter(l=>l.kind==="segment").length} bad-segment-lines=${bad.length}`);
