import { readFileSync } from "node:fs";
import { buildChanAutoDrawResult, diagnoseSegmentEndpoint } from "./chan.bundle.js";
const data = JSON.parse(readFileSync(new URL("./klines.json", import.meta.url), "utf8"));
const { pens, segments } = buildChanAutoDrawResult(data);

// Proper truth: mirror findSegmentEndpointMatch (start/end raw, endpoint pen, adjacent shared pen).
function isRealEndpoint(raw, penIdx) {
  for (let s = 0; s < segments.length; s++) {
    const seg = segments[s];
    const sp = pens[seg.startPenIndex], ep = pens[seg.endPenIndex];
    const prevShared = seg.startPenIndex > 0 ? pens[seg.startPenIndex - 1] : null;
    const nextShared = seg.endPenIndex > 0 ? pens[seg.endPenIndex - 1] : null;
    const mStart = raw === seg.startRawIndex || penIdx === seg.startPenIndex ||
      (!!prevShared && prevShared.endRawIndex === seg.startRawIndex && penIdx === seg.startPenIndex - 1);
    const mEnd = raw === seg.endRawIndex || penIdx === seg.endPenIndex ||
      (!!nextShared && nextShared.endRawIndex === seg.endRawIndex && penIdx === seg.endPenIndex - 1);
    if (mStart || mEnd) return true;
  }
  return false;
}

const probeRaws = new Set();
for (const p of pens) { probeRaws.add(p.startRawIndex); probeRaws.add(p.endRawIndex); }
let mism = 0, checked = 0, over=0, under=0;
for (const r of probeRaws) {
  const bar = data[r]; if (!bar) continue;
  checked++;
  const d = diagnoseSegmentEndpoint(data, bar.timestamp, bar.time);
  const says = d.type === "endpoint" && d.isEndpoint === true;
  const truth = isRealEndpoint(r, locatePen(r));
  if (says !== truth) { mism++; if (says) over++; else under++;
    if (mism<=10) console.log(`MISMATCH raw#${r}: diagnose=${says} truth=${truth} | ${d.explanation?.slice(0,50)}`);
  }
}
function locatePen(raw){ for(let k=0;k<pens.length;k++){const p=pens[k];const a=Math.min(p.startRawIndex,p.endRawIndex),b=Math.max(p.startRawIndex,p.endRawIndex);if(raw>=a&&raw<=b)return k;}return -1;}
console.log(`checked=${checked} mismatches=${mism} (over-claim=${over} under-claim=${under})`);
