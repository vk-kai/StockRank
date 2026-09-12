import { readFileSync, writeFileSync } from "node:fs";
import { buildChanAutoDrawResult } from "./chan.bundle.js";

const data = JSON.parse(readFileSync(new URL("./klines.json", import.meta.url), "utf8"));
const result = buildChanAutoDrawResult(data);

const { pens, segments } = result;

// Build a quick lookup: for each pen, is its start/end a top or bottom?
// A pen "up" starts at a bottom (low) ends at a top (high).
// A pen "down" starts at a top (high) ends at a bottom (low).

console.log(`bars=${data.length} pens=${pens.length} segments=${segments.length}`);

// === Invariant check ===
// Upward segment MUST end at a TOP fractal (high). Downward MUST end at a BOTTOM fractal (low).
// The endPen = pens[endPenIndex]. For confirmed: endPrice = endPen.startPrice.
// Up segment -> endPen should be a "down" pen (start = high = TOP). Down segment -> endPen "up" pen (start=low=BOTTOM).
let violations = [];
for (const s of segments) {
  const endPen = pens[s.endPenIndex];
  if (!endPen) continue;
  const useStart = s.confirmed; // confirmed uses "start", active uses "end"
  const ep = useStart ? endPen.startPrice : endPen.endPrice;
  // The fractal-type of the endpoint:
  // confirmed up-seg: endpoint = down pen start = TOP
  // confirmed down-seg: endpoint = up pen start = BOTTOM
  let expectedPenDirForEndpoint = s.direction === "up" ? "down" : "up";
  let endpointFractal;
  if (useStart) {
    endpointFractal = endPen.direction === "up" ? "BOTTOM(start of up=low)" : "TOP(start of down=high)";
  } else {
    endpointFractal = endPen.direction === "up" ? "TOP(end of up=high)" : "BOTTOM(end of down=low)";
  }
  const ok = useStart ? (endPen.direction === expectedPenDirForEndpoint) : true;
  // Additional geometric check: up segment endPrice must be a local high (>= all in last up pen) and > startPrice
  const geoOk = s.direction === "up" ? ep >= s.startPrice : ep <= s.startPrice;
  if (!ok || !geoOk) {
    violations.push({ segIdx: s.index, dir: s.direction, confirmed: s.confirmed, finishMode: s.finishMode,
      startPenIndex: s.startPenIndex, endPenIndex: s.endPenIndex, startPrice: s.startPrice, endPrice: s.endPrice,
      endPenDir: endPen.direction, endpointFractal, ok, geoOk });
  }
}

console.log("\n=== INVARIANT VIOLATIONS (endpoint fractal wrong) ===", violations.length);
for (const v of violations.slice(0, 40)) console.log(JSON.stringify(v));

// Dump full segments + pens for inspection
writeFileSync(new URL("./segments.json", import.meta.url), JSON.stringify(segments, null, 1));
writeFileSync(new URL("./pens.json", import.meta.url), JSON.stringify(pens.map(p => ({i:p.index,dir:p.direction,s:p.startPrice,e:p.endPrice,stime:p.startTimestamp,etime:p.endTimestamp})), null, 1));

// Print all segments compactly
console.log("\n=== SEGMENTS ===");
for (const s of segments) {
  const endPen = pens[s.endPenIndex];
  const tag = s.direction === "up"
    ? (s.confirmed ? (endPen.direction==="down"?"TOP-ok":`!!BAD endPen=${endPen.direction}`) : "active")
    : (s.confirmed ? (endPen.direction==="up"?"BOTTOM-ok":`!!BAD endPen=${endPen.direction}`) : "active");
  console.log(`seg#${s.index} ${s.direction} ${s.confirmed?"CONF":"act"}(${s.finishMode}) pens[${s.startPenIndex}->${s.endPenIndex}] price ${s.startPrice.toFixed(2)}->${s.endPrice.toFixed(2)} ${tag}`);
}
