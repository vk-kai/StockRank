import { readFileSync } from "node:fs";
import { buildChanAutoDrawResult, diagnoseSegmentEndpoint } from "./chan.bundle.js";
const data = JSON.parse(readFileSync(new URL("./klines.json", import.meta.url), "utf8"));
const { pens, segments } = buildChanAutoDrawResult(data);

// Ground truth: the raw indices that ARE segment endpoints per the drawing.
const trueEndpoints = new Set(); // rawIndex -> direction
const epInfo = {};
for (const s of segments) {
  const startPen = pens[s.startPenIndex];
  const endPen = pens[s.endPenIndex];
  const startRaw = startPen.startRawIndex;
  // active endpoint raw depends on atStart; check both possible
  const endRawConfirmed = endPen.startRawIndex;
  const endRawActiveStart = endPen.startRawIndex;
  const endRawActiveEnd = endPen.endRawIndex;
  trueEndpoints.add(startRaw); epInfo[startRaw] = `start of ${s.direction}#${s.index}`;
  if (s.confirmed) { trueEndpoints.add(endRawConfirmed); epInfo[endRawConfirmed]=`end(conf) of ${s.direction}#${s.index}`; }
  else { /* active: drawing endpoint price is s.endPrice; find which raw */ }
}

// For active segments, the drawn endpoint raw = the raw bar at s.endTimestamp with s.endPrice.
// Map raw bars by timestamp for lookup
const byTs = new Map(data.map(b=>[b.timestamp,b]));
let mismatches = 0, checked = 0;
// Probe every bar that is a pen boundary (candidate endpoint) and some internals
const probeRaws = new Set();
for (const p of pens) { probeRaws.add(p.startRawIndex); probeRaws.add(p.endRawIndex); }
for (const r of probeRaws) {
  const bar = data[r];
  if (!bar) continue;
  checked++;
  const d = diagnoseSegmentEndpoint(data, bar.timestamp, bar.time);
  const diagSaysEndpoint = d.type === "endpoint" && d.isEndpoint;
  // Is this raw a TRUE endpoint of any segment? (check start, and end including active both-sides)
  let isTrue = false;
  for (const s of segments) {
    const sp = pens[s.startPenIndex], ep = pens[s.endPenIndex];
    if (r === sp.startRawIndex) { isTrue = true; break; }
    if (s.confirmed) { if (r === ep.startRawIndex) { isTrue=true; break; } }
    else { if (r === ep.startRawIndex || r === ep.endRawIndex) { isTrue=true; break; } }
  }
  if (diagSaysEndpoint !== isTrue) {
    mismatches++;
    if (mismatches <= 12) console.log(`MISMATCH raw#${r} t=${bar.time}: diagnose.isEndpoint=${diagSaysEndpoint} truth=${isTrue} | diag: ${d.explanation?.slice(0,60)}`);
  }
}
console.log(`\nchecked=${checked} mismatches=${mismatches}`);
