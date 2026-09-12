import type { KlineData } from "../types";

type Direction = "up" | "down";
type FractalType = "top" | "bottom";

interface RawBar extends KlineData {
  rawIndex: number;
}

interface StandardBar {
  index: number;
  high: number;
  low: number;
  rawIndices: number[];
}

interface Fractal {
  index: number;
  type: FractalType;
  stdBarIndex: number;
  price: number;
  rangeHigh: number;
  rangeLow: number;
  rawStart: number;
  rawEnd: number;
  coreRawIndex: number;
}

export interface ChanPen {
  index: number;
  direction: Direction;
  startFractalIndex: number;
  endFractalIndex: number;
  startPrice: number;
  endPrice: number;
  startRawIndex: number;
  endRawIndex: number;
  startTimestamp: number;
  endTimestamp: number;
  confirmed: boolean;
}

export interface ChanSegment {
  index: number;
  direction: Direction;
  startPenIndex: number;
  endPenIndex: number;
  penIndices: number[];
  startPrice: number;
  endPrice: number;
  startTimestamp: number;
  endTimestamp: number;
  confirmed: boolean;
  finishMode: "case1" | "case2" | "active";
  // Raw-bar index of each endpoint. For a confirmed segment the end is the boundary pen's
  // START; for an active segment it is whichever end of the extreme pen holds the directional
  // extreme (may be the pen's START for an up segment whose high sits at a down-pen's start).
  startRawIndex: number;
  endRawIndex: number;
}

export interface AutoDrawLine {
  id: string;
  kind: "pen" | "segment";
  direction: Direction;
  startTimestamp: number;
  startPrice: number;
  endTimestamp: number;
  endPrice: number;
  confirmed: boolean;
  finishMode?: "case1" | "case2" | "active";
}

export interface ChanAutoDrawResult {
  pens: ChanPen[];
  segments: ChanSegment[];
  lines: AutoDrawLine[];
}

interface FeatureElement {
  index: number;
  penIndex: number;
  high: number;
  low: number;
}

interface NormalizedFeatureElement {
  index: number;
  high: number;
  low: number;
  sourcePenIndices: number[];
}

interface FeatureFractal {
  type: FractalType;
  midSourcePenIndex: number;
  price: number;
  hasGapBetween12: boolean;
  sourcePenIndices: number[];
}

interface SegmentFinishDecision {
  confirmed: boolean;
  finishPenIndex: number;
  finishPrice: number;
  finishMode: "case1" | "case2";
}

interface FeatureSequenceAnalysis {
  sequenceKind: "primary" | "secondary";
  segmentDirection: Direction;
  featureDirection: Direction;
  elements: FeatureElement[];
  normalizedElements: NormalizedFeatureElement[];
  fractal: FeatureFractal | null;
}

interface SegmentFinishAnalysis {
  primary: FeatureSequenceAnalysis;
  secondary: FeatureSequenceAnalysis | null;
  decision: SegmentFinishDecision | null;
}

interface SegmentPivotAnalysis {
  pivotPenIndex: number;
  primary: FeatureSequenceAnalysis;
  secondary: FeatureSequenceAnalysis | null;
  finishMode: "case1" | "case2" | null;
}

const RELAXED_PEN_MIN_GAP = 3;

function getBarTradingDate(bar: Pick<KlineData, "time" | "timestamp">) {
  const timeText = typeof bar.time === "string" ? bar.time.trim() : "";
  const matched = timeText.match(/^(\d{4}-\d{2}-\d{2})/);
  if (matched) {
    return matched[1];
  }
  const date = new Date(bar.timestamp * 1000);
  const yyyy = String(date.getFullYear());
  const mm = String(date.getMonth() + 1).padStart(2, "0");
  const dd = String(date.getDate()).padStart(2, "0");
  return `${yyyy}-${mm}-${dd}`;
}

function hasInclusion(a: { high: number; low: number }, b: { high: number; low: number }) {
  return (a.high >= b.high && a.low <= b.low) || (a.high <= b.high && a.low >= b.low);
}

function inferDirection(
  previous: { high: number; low: number },
  next: { high: number; low: number },
  lastDirection: Direction | null
): Direction {
  if (next.high > previous.high && next.low > previous.low) {
    return "up";
  }
  if (next.high < previous.high && next.low < previous.low) {
    return "down";
  }
  if (lastDirection) {
    return lastDirection;
  }
  return next.high >= previous.high ? "up" : "down";
}

function mergeStandardBars(a: StandardBar, b: RawBar, direction: Direction): StandardBar {
  if (direction === "up") {
    return {
      index: a.index,
      high: Math.max(a.high, b.high),
      low: Math.max(a.low, b.low),
      rawIndices: [...a.rawIndices, b.rawIndex],
    };
  }

  return {
    index: a.index,
    high: Math.min(a.high, b.high),
    low: Math.min(a.low, b.low),
    rawIndices: [...a.rawIndices, b.rawIndex],
  };
}

function buildStandardBars(rawBars: RawBar[]): StandardBar[] {
  if (rawBars.length === 0) return [];

  const standardBars: StandardBar[] = [
    {
      index: 0,
      high: rawBars[0].high,
      low: rawBars[0].low,
      rawIndices: [rawBars[0].rawIndex],
    },
  ];

  let lastDirection: Direction | null = null;

  for (let i = 1; i < rawBars.length; i += 1) {
    const nextRaw = rawBars[i];
    const lastStd = standardBars[standardBars.length - 1];
    const currentLikeStd = { high: nextRaw.high, low: nextRaw.low };

    if (hasInclusion(lastStd, currentLikeStd)) {
      const direction = inferDirection(lastStd, currentLikeStd, lastDirection);
      standardBars[standardBars.length - 1] = mergeStandardBars(lastStd, nextRaw, direction);
      lastDirection = direction;
      continue;
    }

    lastDirection = inferDirection(lastStd, currentLikeStd, lastDirection);
    standardBars.push({
      index: standardBars.length,
      high: nextRaw.high,
      low: nextRaw.low,
      rawIndices: [nextRaw.rawIndex],
    });
  }

  return standardBars;
}

function findCoreRawIndex(
  stdBar: StandardBar,
  rawBars: RawBar[],
  type: FractalType
): number {
  let bestIndex = stdBar.rawIndices[0];
  let bestPrice = type === "top" ? Number.NEGATIVE_INFINITY : Number.POSITIVE_INFINITY;

  for (const rawIndex of stdBar.rawIndices) {
    const rawBar = rawBars[rawIndex];
    if (!rawBar) continue;
    const price = type === "top" ? rawBar.high : rawBar.low;
    const isBetter =
      type === "top"
        ? price > bestPrice || (price === bestPrice && rawIndex > bestIndex)
        : price < bestPrice || (price === bestPrice && rawIndex > bestIndex);
    if (isBetter) {
      bestPrice = price;
      bestIndex = rawIndex;
    }
  }

  return bestIndex;
}

function detectFractals(standardBars: StandardBar[], rawBars: RawBar[]): Fractal[] {
  const fractals: Fractal[] = [];

  for (let i = 1; i < standardBars.length - 1; i += 1) {
    const left = standardBars[i - 1];
    const mid = standardBars[i];
    const right = standardBars[i + 1];

    const isTop =
      mid.high > left.high &&
      mid.high > right.high &&
      mid.low > left.low &&
      mid.low > right.low;
    const isBottom =
      mid.low < left.low &&
      mid.low < right.low &&
      mid.high < left.high &&
      mid.high < right.high;

    if (!isTop && !isBottom) {
      continue;
    }

    const type: FractalType = isTop ? "top" : "bottom";
    const fractalRawIndices = [...left.rawIndices, ...mid.rawIndices, ...right.rawIndices];
    fractals.push({
      index: fractals.length,
      type,
      stdBarIndex: i,
      price: type === "top" ? mid.high : mid.low,
      rangeHigh: Math.max(left.high, mid.high, right.high),
      rangeLow: Math.min(left.low, mid.low, right.low),
      rawStart: Math.min(...fractalRawIndices),
      rawEnd: Math.max(...fractalRawIndices),
      coreRawIndex: findCoreRawIndex(mid, rawBars, type),
    });
  }

  return fractals;
}

function pickStrongerFractal(a: Fractal, b: Fractal): Fractal {
  if (a.type !== b.type) return b;
  if (a.type === "top") {
    if (b.price > a.price) return b;
    if (b.price === a.price && b.coreRawIndex >= a.coreRawIndex) return b;
    return a;
  }

  if (b.price < a.price) return b;
  if (b.price === a.price && b.coreRawIndex >= a.coreRawIndex) return b;
  return a;
}

function compressFractals(fractals: Fractal[]): Fractal[] {
  const result: Fractal[] = [];

  for (const fractal of fractals) {
    const last = result[result.length - 1];
    if (!last) {
      result.push(fractal);
      continue;
    }

    if (last.type === fractal.type) {
      result[result.length - 1] = pickStrongerFractal(last, fractal);
      continue;
    }

    result.push(fractal);
  }

  return result.map((item, index) => ({ ...item, index }));
}

function hasOverlap(aStart: number, aEnd: number, bStart: number, bEnd: number) {
  return Math.max(aStart, bStart) <= Math.min(aEnd, bEnd);
}

function isValidPen(start: Fractal, end: Fractal) {
  if (start.type === end.type) return false;
  if (hasOverlap(start.rawStart, start.rawEnd, end.rawStart, end.rawEnd)) return false;
  // Middle continuation fractals cannot form a pen:
  // a later bottom cannot sit entirely above the earlier top,
  // and a later top cannot sit entirely below the earlier bottom.
  if (start.type === "top" && end.rangeLow > start.rangeHigh) return false;
  if (start.type === "bottom" && end.rangeHigh < start.rangeLow) return false;
  return Math.abs(end.coreRawIndex - start.coreRawIndex) - 1 >= RELAXED_PEN_MIN_GAP;
}

function makePen(start: Fractal, end: Fractal, rawBars: RawBar[], index: number): ChanPen {
  return {
    index,
    direction: start.type === "bottom" ? "up" : "down",
    startFractalIndex: start.index,
    endFractalIndex: end.index,
    startPrice: start.price,
    endPrice: end.price,
    startRawIndex: start.coreRawIndex,
    endRawIndex: end.coreRawIndex,
    startTimestamp: rawBars[start.coreRawIndex].timestamp,
    endTimestamp: rawBars[end.coreRawIndex].timestamp,
    confirmed: true,
  };
}

function normalizePenConnections(pens: ChanPen[]): ChanPen[] {
  if (pens.length === 0) {
    return [];
  }

  const normalized: ChanPen[] = [{ ...pens[0], index: 0 }];

  for (let i = 1; i < pens.length; i += 1) {
    const current = { ...pens[i], index: normalized.length };
    const prev = normalized[normalized.length - 1];

    if (
      current.startRawIndex !== prev.endRawIndex ||
      current.startPrice !== prev.endPrice ||
      current.startTimestamp !== prev.endTimestamp
    ) {
      // Later surviving same-type fractals should replace the old shared pivot,
      // rather than forcing the next pen back to an already-invalidated endpoint.
      prev.endFractalIndex = current.startFractalIndex;
      prev.endPrice = current.startPrice;
      prev.endRawIndex = current.startRawIndex;
      prev.endTimestamp = current.startTimestamp;
    }

    normalized.push(current);
  }

  return normalized;
}

function mergeSameDirectionPens(pens: ChanPen[]): ChanPen[] {
  if (pens.length <= 1) {
    return pens;
  }

  const merged: ChanPen[] = [];
  for (const pen of pens) {
    const last = merged[merged.length - 1];
    if (!last) {
      merged.push({ ...pen });
      continue;
    }

    if (last.direction !== pen.direction) {
      merged.push({ ...pen });
      continue;
    }

    merged[merged.length - 1] = {
      ...last,
      endFractalIndex: pen.endFractalIndex,
      endPrice: pen.endPrice,
      endRawIndex: pen.endRawIndex,
      endTimestamp: pen.endTimestamp,
      confirmed: last.confirmed && pen.confirmed,
    };
  }

  return merged.map((pen, index) => {
    if (index === 0) {
      return { ...pen, index: 0 };
    }

    const prev = merged[index - 1];
    return {
      ...pen,
      index,
      startFractalIndex: prev.endFractalIndex,
      startPrice: prev.endPrice,
      startRawIndex: prev.endRawIndex,
      startTimestamp: prev.endTimestamp,
    };
  });
}

function mergeSameDirectionSegments(segments: ChanSegment[]): ChanSegment[] {
  if (segments.length <= 1) {
    return segments;
  }

  const merged: ChanSegment[] = [];
  for (const segment of segments) {
    const last = merged[merged.length - 1];
    if (!last) {
      merged.push({ ...segment });
      continue;
    }

    if (last.direction !== segment.direction) {
      merged.push({ ...segment });
      continue;
    }

    merged[merged.length - 1] = {
      ...last,
      endPenIndex: segment.endPenIndex,
      penIndices: Array.from(
        { length: segment.endPenIndex - last.startPenIndex + 1 },
        (_, offset) => last.startPenIndex + offset
      ),
      endPrice: segment.endPrice,
      endTimestamp: segment.endTimestamp,
      confirmed: last.confirmed && segment.confirmed,
      finishMode: segment.finishMode,
    };
  }

  return merged.map((segment, index) => {
    if (index === 0) {
      return { ...segment, index: 0 };
    }

    const prev = merged[index - 1];
    return {
      ...segment,
      index,
      startPenIndex: prev.endPenIndex,
      penIndices: Array.from(
        { length: segment.endPenIndex - prev.endPenIndex + 1 },
        (_, offset) => prev.endPenIndex + offset
      ),
      startPrice: prev.endPrice,
      startTimestamp: prev.endTimestamp,
      direction: prev.direction === "up" ? "down" : "up",
    };
  });
}


function buildPens(fractals: Fractal[], rawBars: RawBar[]): ChanPen[] {
  if (fractals.length < 2) return [];

  const pens: ChanPen[] = [];
  let start = fractals[0];
  let endCandidate: Fractal | null = null;

  for (let i = 1; i < fractals.length; i += 1) {
    const current = fractals[i];

    if (!endCandidate) {
      if (current.type === start.type) {
        start = pickStrongerFractal(start, current);
        continue;
      }

      if (isValidPen(start, current)) {
        endCandidate = current;
      }
      continue;
    }

    if (current.type === endCandidate.type) {
      endCandidate = pickStrongerFractal(endCandidate, current);
      continue;
    }

    const startInvalidated =
      start.type === "top" ? current.price > start.price : current.price < start.price;

    if (startInvalidated) {
      // 出现了更强的同类分型，说明原起点只是中继分型，整笔起点要顺延到这里。
      start = current;
      endCandidate = null;
      continue;
    }

    // 只有当回抽的同类分型没有破坏原起点时，前一笔才真正确认。
    pens.push(makePen(start, endCandidate, rawBars, pens.length));
    start = endCandidate;
    endCandidate = isValidPen(start, current) ? current : null;
  }

  return mergeSameDirectionPens(normalizePenConnections(pens));
}

function getPenHigh(pen: ChanPen) {
  return Math.max(pen.startPrice, pen.endPrice);
}

function getPenLow(pen: ChanPen) {
  return Math.min(pen.startPrice, pen.endPrice);
}

function hasThreePenOverlap(pens: ChanPen[]) {
  if (pens.length < 3) return false;
  const lows = pens.map((pen) => getPenLow(pen));
  const highs = pens.map((pen) => getPenHigh(pen));
  return Math.max(...lows) <= Math.min(...highs);
}

function trySeedSegment(pens: ChanPen[], startIndex: number) {
  if (startIndex + 2 >= pens.length) return null;
  const window = pens.slice(startIndex, startIndex + 3);
  if (window[0].direction !== window[2].direction) return null;
  if (window[0].direction === window[1].direction) return null;
  if (!hasThreePenOverlap(window)) return null;
  return {
    direction: window[0].direction,
    startPenIndex: startIndex,
    endPenIndex: startIndex + 2,
    penIndices: [startIndex, startIndex + 1, startIndex + 2],
  };
}

function buildFeatureSequence(
  pens: ChanPen[],
  segmentDirection: Direction,
  startPenIndex: number,
  endPenIndex: number,
  featureDirection: Direction
) {
  const result: FeatureElement[] = [];
  for (let i = startPenIndex; i <= endPenIndex; i += 1) {
    const pen = pens[i];
    if (!pen || pen.direction !== featureDirection) continue;
    result.push({
      index: result.length,
      penIndex: i,
      high: getPenHigh(pen),
      low: getPenLow(pen),
    });
  }
  if (segmentDirection === "up" || segmentDirection === "down") {
    return result;
  }
  return result;
}

function normalizeFeatureSequence(
  elements: FeatureElement[],
  options?: { preserveLeadingPair?: boolean }
): NormalizedFeatureElement[] {
  if (elements.length === 0) return [];
  const preserveLeadingPair = options?.preserveLeadingPair === true;

  if (preserveLeadingPair && elements.length >= 2) {
    const result: NormalizedFeatureElement[] = [
      {
        index: 0,
        high: elements[0].high,
        low: elements[0].low,
        sourcePenIndices: [elements[0].penIndex],
      },
      {
        index: 1,
        high: elements[1].high,
        low: elements[1].low,
        sourcePenIndices: [elements[1].penIndex],
      },
    ];

    let lastDirection: Direction | null = inferDirection(elements[0], elements[1], null);

    for (let i = 2; i < elements.length; i += 1) {
      const next = elements[i];
      const last = result[result.length - 1];

      if (hasInclusion(last, next)) {
        const direction = inferDirection(last, next, lastDirection);
        result[result.length - 1] =
          direction === "up"
            ? {
                index: last.index,
                high: Math.max(last.high, next.high),
                low: Math.max(last.low, next.low),
                sourcePenIndices: [...last.sourcePenIndices, next.penIndex],
              }
            : {
                index: last.index,
                high: Math.min(last.high, next.high),
                low: Math.min(last.low, next.low),
                sourcePenIndices: [...last.sourcePenIndices, next.penIndex],
              };
        lastDirection = direction;
        continue;
      }

      lastDirection = inferDirection(last, next, lastDirection);
      result.push({
        index: result.length,
        high: next.high,
        low: next.low,
        sourcePenIndices: [next.penIndex],
      });
    }

    return result;
  }

  const result: NormalizedFeatureElement[] = [
    {
      index: 0,
      high: elements[0].high,
      low: elements[0].low,
      sourcePenIndices: [elements[0].penIndex],
    },
  ];

  let lastDirection: Direction | null = null;

  for (let i = 1; i < elements.length; i += 1) {
    const next = elements[i];
    const last = result[result.length - 1];

    if (hasInclusion(last, next)) {
      const direction = inferDirection(last, next, lastDirection);
      result[result.length - 1] =
        direction === "up"
          ? {
              index: last.index,
              high: Math.max(last.high, next.high),
              low: Math.max(last.low, next.low),
              sourcePenIndices: [...last.sourcePenIndices, next.penIndex],
            }
          : {
              index: last.index,
              high: Math.min(last.high, next.high),
              low: Math.min(last.low, next.low),
              sourcePenIndices: [...last.sourcePenIndices, next.penIndex],
            };
      lastDirection = direction;
      continue;
    }

    lastDirection = inferDirection(last, next, lastDirection);
    result.push({
      index: result.length,
      high: next.high,
      low: next.low,
      sourcePenIndices: [next.penIndex],
    });
  }

  return result;
}

function detectFeatureFractal(
  normalized: NormalizedFeatureElement[],
  requiredType: FractalType,
  strict: boolean = false,
  // When >= 0, skip any fractal whose middle element sits at/before this source pen.
  // Used after a segment finish is "destroyed": we only want the NEXT fractal past the break.
  afterSourcePenIndex: number = -1
): FeatureFractal | null {
  for (let i = 1; i < normalized.length - 1; i += 1) {
    const left = normalized[i - 1];
    const mid = normalized[i];
    const right = normalized[i + 1];

    // Chan theory (Lesson 67): a feature-sequence fractal follows the SAME definition as
    // an ordinary K-line fractal — i.e. only the relevant extreme matters:
    //   Top:    mid.high is strictly the highest of the three
    //   Bottom: mid.low  is strictly the lowest  of the three
    // The 4-condition form (also requiring the low/high) is only equivalent AFTER perfect
    // inclusion processing; with the dividing-point rule the leading pair isn't merged, so
    // the 4-condition test wrongly rejects valid fractals (e.g. a top whose bar has a long
    // lower shadow). The 2-condition test is the theory-faithful default.
    const isTop = strict
      ? (mid.high > left.high && mid.high > right.high &&
         mid.low > left.low && mid.low > right.low)
      : (mid.high > left.high && mid.high > right.high);
    const isBottom = strict
      ? (mid.low < left.low && mid.low < right.low &&
         mid.high < left.high && mid.high < right.high)
      : (mid.low < left.low && mid.low < right.low);

    if ((requiredType === "top" && !isTop) || (requiredType === "bottom" && !isBottom)) {
      continue;
    }

    const midSourcePenIndex = mid.sourcePenIndices[mid.sourcePenIndices.length - 1];
    if (afterSourcePenIndex >= 0 && midSourcePenIndex <= afterSourcePenIndex) {
      continue;
    }

    const hasGapBetween12 = Math.max(left.low, mid.low) > Math.min(left.high, mid.high);
    return {
      type: requiredType,
      midSourcePenIndex,
      price: requiredType === "top" ? mid.high : mid.low,
      hasGapBetween12,
      sourcePenIndices: [...left.sourcePenIndices, ...mid.sourcePenIndices, ...right.sourcePenIndices],
    };
  }

  return null;
}

function makeFeatureSequenceAnalysis(
  sequenceKind: "primary" | "secondary",
  pens: ChanPen[],
  segmentDirection: Direction,
  startPenIndex: number,
  endPenIndex: number,
  featureDirection: Direction,
  requiredType: FractalType,
  options?: { preserveLeadingPair?: boolean }
): FeatureSequenceAnalysis {
  const elements = buildFeatureSequence(
    pens,
    segmentDirection,
    startPenIndex,
    endPenIndex,
    featureDirection
  );
  const normalizedElements = normalizeFeatureSequence(elements, {
    preserveLeadingPair: true,
    ...options,
  });
  return {
    sequenceKind,
    segmentDirection,
    featureDirection,
    elements,
    normalizedElements,
    fractal: detectFeatureFractal(normalizedElements, requiredType),
  };
}

function isBasicSegmentPivotCandidate(
  pens: ChanPen[],
  pivotPenIndex: number,
  segmentDirection: Direction
) {
  const pivotPen = pens[pivotPenIndex];
  const prevPen = pens[pivotPenIndex - 1];
  const boundaryPenDirection: Direction = segmentDirection === "up" ? "down" : "up";

  if (!pivotPen || !prevPen) {
    return false;
  }
  if (pivotPen.direction !== boundaryPenDirection) {
    return false;
  }
  if (prevPen.direction === pivotPen.direction) {
    return false;
  }

  // A segment turning point must be a real shared pivot between two opposite pens.
  return (
    pivotPen.startRawIndex === prevPen.endRawIndex &&
    pivotPen.startTimestamp === prevPen.endTimestamp
  );
}

function resolveSegmentBoundaryPenIndex(
  pens: ChanPen[],
  startPenIndex: number,
  searchEndPenIndex: number,
  segmentDirection: Direction,
  candidatePenIndices?: number[],
  fallbackMidPenIndex?: number,
  fallbackPrice?: number
) {
  const boundaryPenDirection: Direction = segmentDirection === "up" ? "down" : "up";
  let bestPenIndex = -1;
  let bestPrice =
    segmentDirection === "up" ? Number.NEGATIVE_INFINITY : Number.POSITIVE_INFINITY;
  const allowedPenIndices = candidatePenIndices ? new Set(candidatePenIndices) : null;

  // Pass 1: strict search — only pens that satisfy isBasicSegmentPivotCandidate
  for (let i = startPenIndex + 1; i <= searchEndPenIndex; i += 1) {
    if (allowedPenIndices && !allowedPenIndices.has(i)) {
      continue;
    }
    const pen = pens[i];
    if (!pen || pen.direction !== boundaryPenDirection) {
      continue;
    }
    if (!isBasicSegmentPivotCandidate(pens, i, segmentDirection)) {
      continue;
    }

    const better =
      segmentDirection === "up"
        ? pen.startPrice > bestPrice
        : pen.startPrice < bestPrice;
    const samePriceEarlier = pen.startPrice === bestPrice && i < bestPenIndex;

    if (better || samePriceEarlier) {
      bestPenIndex = i;
      bestPrice = pen.startPrice;
    }
  }

  // Pass 2 (fallback): if strict search found nothing, relax the pivot candidate check.
  // Just find the boundary-direction pen with the best price in the fractal range.
  // This handles cases where pen boundaries don't perfectly align due to fractal compression.
  if (bestPenIndex < 0) {
    for (let i = startPenIndex + 1; i <= searchEndPenIndex; i += 1) {
      if (allowedPenIndices && !allowedPenIndices.has(i)) {
        continue;
      }
      const pen = pens[i];
      if (!pen || pen.direction !== boundaryPenDirection) {
        continue;
      }

      const better =
        segmentDirection === "up"
          ? pen.startPrice > bestPrice
          : pen.startPrice < bestPrice;
      const samePriceEarlier = pen.startPrice === bestPrice && i < bestPenIndex;

      if (better || samePriceEarlier) {
        bestPenIndex = i;
        bestPrice = pen.startPrice;
      }
    }
  }

  // Pass 3 (last resort): use the fractal's mid element pen index and price directly
  if (bestPenIndex < 0 && fallbackMidPenIndex !== undefined && fallbackPrice !== undefined) {
    bestPenIndex = fallbackMidPenIndex;
    bestPrice = fallbackPrice;
  }

  return {
    finishPenIndex: bestPenIndex,
    finishPrice: bestPrice,
  };
}

function expandFeatureFractalPenRange(sourcePenIndices: number[]) {
  if (sourcePenIndices.length === 0) {
    return [];
  }
  const minPenIndex = Math.min(...sourcePenIndices);
  const maxPenIndex = Math.max(...sourcePenIndices);
  return Array.from({ length: maxPenIndex - minPenIndex + 1 }, (_, offset) => minPenIndex + offset);
}

function analyzeSegmentFinish(
  pens: ChanPen[],
  startPenIndex: number,
  endPenIndex: number,
  segmentDirection: Direction,
  afterSourcePenIndex: number = -1
): SegmentFinishAnalysis {
  const segmentStartPrice = pens[startPenIndex]?.startPrice ?? NaN;
  const isBoundaryDirectionValid = (finishPrice: number) =>
    segmentDirection === "up" ? finishPrice > segmentStartPrice : finishPrice < segmentStartPrice;
  const primaryFeatureDirection: Direction = segmentDirection === "up" ? "down" : "up";
  const primaryRequiredType: FractalType = segmentDirection === "up" ? "top" : "bottom";

  // Try multiple normalization strategies to find a fractal.
  // Strategy 1: full normalization (no preserveLeadingPair) — standard Chan theory inclusion processing.
  // Strategy 2: preserveLeadingPair — preserves first two elements (current behavior, as fallback).
  // Strategy 3: no normalization at all (raw elements) — most lenient, last resort.
  const normalizationStrategies: Array<{ preserveLeadingPair?: boolean; noNormalize?: boolean }> = [
    {},
    { preserveLeadingPair: true },
    { noNormalize: true },
  ];

  let primary: FeatureSequenceAnalysis | null = null;

  for (const strategy of normalizationStrategies) {
    const elements = buildFeatureSequence(
      pens,
      segmentDirection,
      startPenIndex,
      endPenIndex,
      primaryFeatureDirection
    );
    let normalizedElements: NormalizedFeatureElement[];
    if (strategy.noNormalize) {
      normalizedElements = elements.map((el) => ({
        index: el.index,
        high: el.high,
        low: el.low,
        sourcePenIndices: [el.penIndex],
      }));
    } else {
      normalizedElements = normalizeFeatureSequence(elements, {
        preserveLeadingPair: strategy.preserveLeadingPair === true,
      });
    }
    const fractal = detectFeatureFractal(normalizedElements, primaryRequiredType, false, afterSourcePenIndex);
    if (fractal) {
      primary = {
        sequenceKind: "primary",
        segmentDirection,
        featureDirection: primaryFeatureDirection,
        elements,
        normalizedElements,
        fractal,
      };
      break;
    }
  }

  // If no fractal found with any strategy, segment cannot finish
  if (!primary || !primary.fractal) {
    return {
      primary: primary ?? makeFeatureSequenceAnalysis(
        "primary", pens, segmentDirection, startPenIndex, endPenIndex,
        primaryFeatureDirection, primaryRequiredType, { preserveLeadingPair: true }
      ),
      secondary: null,
      decision: null,
    };
  }

  // Case 1: no gap between elements 1 and 2 of the fractal
  if (!primary.fractal.hasGapBetween12) {
    const boundary = resolveSegmentBoundaryPenIndex(
      pens,
      startPenIndex,
      endPenIndex,
      segmentDirection,
      expandFeatureFractalPenRange(primary.fractal.sourcePenIndices),
      primary.fractal.midSourcePenIndex,
      primary.fractal.price
    );
    return {
      primary,
      secondary: null,
      decision:
        boundary.finishPenIndex < 0 || !isBoundaryDirectionValid(boundary.finishPrice)
          ? null
          : {
              confirmed: true,
              finishPenIndex: boundary.finishPenIndex,
              finishPrice: boundary.finishPrice,
              finishMode: "case1",
            },
    };
  }

  // Case 2: gap between elements 1 and 2 — need secondary feature sequence confirmation
  const secondaryFeatureDirection: Direction = segmentDirection;
  const secondaryRequiredType: FractalType = segmentDirection === "up" ? "bottom" : "top";
  const secondary = makeFeatureSequenceAnalysis(
    "secondary",
    pens,
    segmentDirection,
    primary.fractal.midSourcePenIndex + 1,
    endPenIndex,
    secondaryFeatureDirection,
    secondaryRequiredType,
    { preserveLeadingPair: true }
  );
  const boundary = resolveSegmentBoundaryPenIndex(
    pens,
    startPenIndex,
    endPenIndex,
    segmentDirection,
    expandFeatureFractalPenRange(primary.fractal.sourcePenIndices),
    primary.fractal.midSourcePenIndex,
    primary.fractal.price
  );

  return {
    primary,
    secondary,
    decision:
      !secondary.fractal ||
      boundary.finishPenIndex < 0 ||
      !isBoundaryDirectionValid(boundary.finishPrice)
        ? null
        : {
            confirmed: true,
            finishPenIndex: boundary.finishPenIndex,
            finishPrice: boundary.finishPrice,
            finishMode: "case2",
          },
  };
}

function tryConfirmSegmentFinish(
  pens: ChanPen[],
  startPenIndex: number,
  endPenIndex: number,
  segmentDirection: Direction,
  afterSourcePenIndex: number = -1
): SegmentFinishDecision | null {
  return analyzeSegmentFinish(pens, startPenIndex, endPenIndex, segmentDirection, afterSourcePenIndex).decision;
}

function makeSegment(
  pens: ChanPen[],
  index: number,
  startPenIndex: number,
  endPenIndex: number,
  finishMode: "case1" | "case2" | "active",
  confirmed: boolean,
  endPointAt: "start" | "end"
): ChanSegment {
  const startPen = pens[startPenIndex];
  const endPen = pens[endPenIndex];
  const direction = startPen.direction;
  const endPrice = endPointAt === "start" ? endPen.startPrice : endPen.endPrice;
  const endTimestamp = endPointAt === "start" ? endPen.startTimestamp : endPen.endTimestamp;
  const endRawIndex = endPointAt === "start" ? endPen.startRawIndex : endPen.endRawIndex;
  return {
    index,
    direction,
    startPenIndex,
    endPenIndex,
    penIndices: Array.from(
      { length: endPenIndex - startPenIndex + 1 },
      (_, offset) => startPenIndex + offset
    ),
    startPrice: startPen.startPrice,
    endPrice,
    startTimestamp: startPen.startTimestamp,
    endTimestamp,
    startRawIndex: startPen.startRawIndex,
    endRawIndex,
    confirmed,
    finishMode,
  };
}

type ResolvedSegmentFinish =
  | { kind: "confirmed"; finishPenIndex: number; finishMode: "case1" | "case2"; afterSourcePenIndex: number }
  | { kind: "active"; afterSourcePenIndex: number };

// Find the pen that carries the directional extreme over [startPenIndex, endPenIndex]:
// the highest high for an up segment, the lowest low for a down segment.
function findDirectionalExtremePen(
  pens: ChanPen[],
  startPenIndex: number,
  endPenIndex: number,
  direction: Direction
): { penIndex: number; atStart: boolean } | null {
  let bestPenIndex = -1;
  let bestPrice = direction === "up" ? Number.NEGATIVE_INFINITY : Number.POSITIVE_INFINITY;
  for (let i = startPenIndex; i <= endPenIndex; i += 1) {
    const pen = pens[i];
    if (!pen) continue;
    const price = direction === "up" ? getPenHigh(pen) : getPenLow(pen);
    const better = direction === "up" ? price > bestPrice : price < bestPrice;
    if (better) {
      bestPrice = price;
      bestPenIndex = i;
    }
  }
  if (bestPenIndex < 0) return null;
  // The extreme sits at the END of a same-direction pen, or the START of an opposite pen.
  const pen = pens[bestPenIndex];
  const atStart = direction === "up" ? pen.direction === "down" : pen.direction === "up";
  return { penIndex: bestPenIndex, atStart };
}

// Chan theory Lesson 78: a (provisional) finish only becomes final once the reversal that
// starts at the finish point develops into a real opposite segment. If, before that opposite
// segment confirms, price makes a NEW extreme in the original segment's direction — i.e. it
// "breaks the damaging pen's bottom/top" — the finish is destroyed and the original segment
// continues. (Rule D in the design notes.)
function checkSegmentFinishDestruction(
  pens: ChanPen[],
  finish: SegmentFinishDecision,
  direction: Direction
): { destroyed: boolean; breakPenIndex: number } {
  const oppositeDirection: Direction = direction === "up" ? "down" : "up";
  const finishPenIndex = finish.finishPenIndex;
  const finishPrice = finish.finishPrice;
  const oppositeSeedValid = !!trySeedSegment(pens, finishPenIndex);

  for (let k = finishPenIndex + 1; k < pens.length; k += 1) {
    // Did the reversal already confirm an opposite-direction segment? => finish is final.
    if (oppositeSeedValid) {
      const oppositeFinish = tryConfirmSegmentFinish(pens, finishPenIndex, k, oppositeDirection);
      if (oppositeFinish) {
        return { destroyed: false, breakPenIndex: -1 };
      }
    }
    // Did this pen make a new extreme in the segment's own direction past the finish?
    const pen = pens[k];
    const breaks =
      direction === "up" ? getPenHigh(pen) > finishPrice : getPenLow(pen) < finishPrice;
    if (breaks) {
      return { destroyed: true, breakPenIndex: k };
    }
  }
  return { destroyed: false, breakPenIndex: -1 };
}

// Resolve a segment's finish with destruction re-validation. Each candidate finish is
// provisional; if it is destroyed we keep scanning for a LATER fractal (via afterSourcePenIndex)
// until one survives. Returns "active" if none survives.
function resolveSegmentFinish(
  pens: ChanPen[],
  seed: { startPenIndex: number; endPenIndex: number; direction: Direction }
): ResolvedSegmentFinish {
  const direction = seed.direction;
  let afterSourcePenIndex = -1;

  for (let j = seed.endPenIndex + 1; j < pens.length; j += 1) {
    const decision = tryConfirmSegmentFinish(
      pens,
      seed.startPenIndex,
      j,
      direction,
      afterSourcePenIndex
    );
    if (!decision) {
      continue;
    }
    const destruction = checkSegmentFinishDestruction(pens, decision, direction);
    if (!destruction.destroyed) {
      return {
        kind: "confirmed",
        finishPenIndex: decision.finishPenIndex,
        finishMode: decision.finishMode,
        afterSourcePenIndex,
      };
    }
    // Finish destroyed: the segment continues past the break, so require the next fractal
    // to sit strictly beyond the breaking pen.
    afterSourcePenIndex = Math.max(afterSourcePenIndex, destruction.breakPenIndex);
  }

  return { kind: "active", afterSourcePenIndex };
}

function buildSegments(pens: ChanPen[]): ChanSegment[] {
  const segments: ChanSegment[] = [];
  let i = 0;

  while (i < pens.length - 2) {
    const seed = trySeedSegment(pens, i);
    if (!seed) {
      i += 1;
      continue;
    }

    const resolved = resolveSegmentFinish(pens, seed);

    if (resolved.kind === "active") {
      // No confirmed finish: the segment is still forming. Its endpoint is the directional
      // EXTREME reached so far — never the trailing pullback — so an up segment can never be
      // drawn ending at a bottom (and a down segment never at a top).
      const extreme = findDirectionalExtremePen(pens, seed.startPenIndex, pens.length - 1, seed.direction);
      if (!extreme || extreme.penIndex <= seed.startPenIndex) {
        break;
      }
      segments.push(
        makeSegment(
          pens,
          segments.length,
          seed.startPenIndex,
          extreme.penIndex,
          "active",
          false,
          extreme.atStart ? "start" : "end"
        )
      );
      break;
    }

    segments.push(
      makeSegment(
        pens,
        segments.length,
        seed.startPenIndex,
        resolved.finishPenIndex,
        resolved.finishMode,
        true,
        "start"
      )
    );
    i = resolved.finishPenIndex;
  }

  return segments
    .filter((segment) => segment.endTimestamp > segment.startTimestamp)
    .map((segment, index) => ({ ...segment, index }));
}

export interface FractalDiagnosis {
  type: FractalType | "none";
  elementRole?: "first" | "second" | "third";
  isExtreme?: boolean; // For second element, is it the highest/lowest raw bar?
  explanation: string;
}

export interface SegmentEndpointDiagnosis {
  type: "endpoint" | "none";
  isEndpoint?: boolean;
  segmentDirection?: Direction;
  penIndex?: number;
  pivotRawIndex?: number;
  leftFractalType?: FractalType;
  rightFractalType?: FractalType;
  leftHasGapBetween12?: boolean;
  finishMode?: "case1" | "case2";
  explanation: string;
}

interface SegmentEndpointDiagnosisMatch extends SegmentEndpointDiagnosis {
  _priority: number;
  _sequenceEndPenIndex: number;
}

function getEffectiveFractalIndicesFromPens(pens: ChanPen[]) {
  const indices = new Set<number>();
  for (const pen of pens) {
    indices.add(pen.startFractalIndex);
    indices.add(pen.endFractalIndex);
  }
  return indices;
}

function locateFractalElement(
  standardBars: StandardBar[],
  fractal: Fractal,
  targetRawIndex: number
): { elementRole: "first" | "second" | "third"; isExtreme: boolean } | null {
  const leftStd = standardBars[fractal.stdBarIndex - 1];
  const midStd = standardBars[fractal.stdBarIndex];
  const rightStd = standardBars[fractal.stdBarIndex + 1];

  if (!leftStd || !midStd || !rightStd) {
    return null;
  }

  if (leftStd.rawIndices.includes(targetRawIndex)) {
    return { elementRole: "first", isExtreme: false };
  }
  if (midStd.rawIndices.includes(targetRawIndex)) {
    return {
      elementRole: "second",
      isExtreme: targetRawIndex === fractal.coreRawIndex,
    };
  }
  if (rightStd.rawIndices.includes(targetRawIndex)) {
    return { elementRole: "third", isExtreme: false };
  }

  return null;
}

function locateTargetPenIndex(pens: ChanPen[], targetRawIndex: number) {
  return pens.findIndex((pen) => {
    const start = Math.min(pen.startRawIndex, pen.endRawIndex);
    const end = Math.max(pen.startRawIndex, pen.endRawIndex);
    return targetRawIndex >= start && targetRawIndex <= end;
  });
}

function buildSegmentEndpointDiagnosis(
  pens: ChanPen[],
  targetRawIndex: number,
  targetPenIndex: number
): SegmentEndpointDiagnosis | null {
  let bestMatch: SegmentEndpointDiagnosisMatch | null = null;

  // Walk the SAME destruction-aware segments the drawing uses, so the verdict never disagrees
  // with the drawn line (e.g. it never reports a destroyed finish as an endpoint).
  let i = 0;
  while (i < pens.length - 2) {
    const seed = trySeedSegment(pens, i);
    if (!seed) {
      i += 1;
      continue;
    }
    const resolved = resolveSegmentFinish(pens, seed);
    if (resolved.kind === "active") {
      // The active tail's temporary endpoint is explained by the caller's active-tail branch.
      break;
    }

    const finishPenIndex = resolved.finishPenIndex;
    // Only the segment whose pen range actually contains the target is relevant.
    if (targetPenIndex >= seed.startPenIndex && targetPenIndex <= finishPenIndex) {
      const probeJ = Math.min(finishPenIndex + 2, pens.length - 1);
      const analysis = analyzeSegmentFinish(
        pens,
        seed.startPenIndex,
        probeJ,
        seed.direction,
        resolved.afterSourcePenIndex
      );
      const finishPen = pens[finishPenIndex];
      const isEndpoint = !!finishPen && targetRawIndex === finishPen.startRawIndex;
      const inFinishPen = !!finishPen && targetPenIndex === finishPenIndex;
      const leftType = analysis.primary.fractal?.type;
      const rightType = analysis.secondary?.fractal?.type;
      const upText = analysis.primary.segmentDirection === "up" ? "上" : "下";

      let explanation: string;
      if (isEndpoint) {
        explanation = `该K线就是向${upText}线段的端点。红框里的特征序列在去包含后的标准特征序列中已经形成${leftType === "top" ? "顶" : "底"}分型，因此该分型覆盖区域里的${analysis.primary.segmentDirection === "up" ? "最高" : "最低"}K线被取为拐点。${
          analysis.decision?.finishMode === "case2"
            ? `当前属于第二种情况，主特征序列分型之间有缺口，右侧第二特征序列也已形成${rightType === "top" ? "顶" : "底"}分型，故端点最终成立。`
            : "当前属于第一种情况，主特征序列分型成立后直接确认端点。"
        }`;
      } else if (inFinishPen) {
        explanation = `该K线位于端点所在笔（第${finishPenIndex + 1}笔）内，但它不是端点本身；真正被取作端点的是这笔起点那根K线。`;
      } else {
        explanation = `该K线位于向${upText}线段内部，不是线段端点。线段端点只会出现在该方向上的顶/底分型处；即使此处曾形成过特征分型候选，只要后续走势破坏了它，这里就不是最终端点。`;
      }

      const priority = (isEndpoint ? 100 : inFinishPen ? 50 : 10) + finishPenIndex;
      if (!bestMatch || bestMatch._priority < priority) {
        bestMatch = {
          type: isEndpoint ? "endpoint" : "none",
          isEndpoint,
          segmentDirection: analysis.primary.segmentDirection,
          penIndex: finishPenIndex,
          pivotRawIndex: finishPen?.startRawIndex ?? targetRawIndex,
          leftFractalType: leftType,
          rightFractalType: rightType,
          leftHasGapBetween12: analysis.primary.fractal?.hasGapBetween12,
          finishMode: analysis.decision?.finishMode,
          explanation,
          _priority: priority,
          _sequenceEndPenIndex: finishPenIndex,
        };
      }
    }

    i = finishPenIndex;
  }

  return bestMatch;
}

function findSegmentEndpointMatch(
  pens: ChanPen[],
  segments: ChanSegment[],
  targetRawIndex: number,
  targetPenIndex: number
): SegmentEndpointDiagnosis | null {
  for (let i = 0; i < segments.length; i += 1) {
    const segment = segments[i];
    const startPen = pens[segment.startPenIndex];
    const endPen = pens[segment.endPenIndex];
    const prevStartSharedPen = segment.startPenIndex > 0 ? pens[segment.startPenIndex - 1] : null;
    const nextEndSharedPen = segment.endPenIndex > 0 ? pens[segment.endPenIndex - 1] : null;
    if (!startPen || !endPen) {
      continue;
    }

    const startRawIndex = segment.startRawIndex;
    const endRawIndex = segment.endRawIndex;
    const matchesStartEndpoint =
      targetRawIndex === startRawIndex ||
      targetPenIndex === segment.startPenIndex ||
      (!!prevStartSharedPen &&
        prevStartSharedPen.endRawIndex === startRawIndex &&
        targetPenIndex === segment.startPenIndex - 1);
    const matchesEndEndpoint =
      targetRawIndex === endRawIndex ||
      targetPenIndex === segment.endPenIndex ||
      (!!nextEndSharedPen &&
        nextEndSharedPen.endRawIndex === endRawIndex &&
        targetPenIndex === segment.endPenIndex - 1);

    if (matchesStartEndpoint) {
      const prevSegment = i > 0 ? segments[i - 1] : null;
      return {
        type: "endpoint",
        isEndpoint: true,
        segmentDirection: segment.direction,
        penIndex: segment.startPenIndex,
        pivotRawIndex: startRawIndex,
        finishMode: prevSegment?.finishMode === "active" ? undefined : prevSegment?.finishMode,
        explanation: prevSegment
          ? targetRawIndex === startRawIndex || targetPenIndex === segment.startPenIndex
            ? `该K线是向${segment.direction === "up" ? "上" : "下"}线段的起始端点，同时也是前一向${prevSegment.direction === "up" ? "上" : "下"}线段的结束端点。按缠论口径，线段交界处就是前后两段共享的拐点，因此这里属于有效端点。`
            : `该K线位于线段起始拐点相邻共享笔中。按缠论口径，线段交界处是前后两笔共享的同一个拐点，因此这里也应视为命中了该端点。`
          : targetRawIndex === startRawIndex || targetPenIndex === segment.startPenIndex
          ? `该K线是当前已识别线段序列的起始端点。`
          : `该K线位于当前已识别线段起始拐点相邻共享笔中，因此这里也命中了该端点。`,
      };
    }

    if (matchesEndEndpoint) {
      return segment.confirmed
        ? {
            type: "endpoint",
            isEndpoint: true,
            segmentDirection: segment.direction,
            penIndex: segment.endPenIndex,
            pivotRawIndex: endRawIndex,
            finishMode: segment.finishMode === "active" ? undefined : segment.finishMode,
            explanation:
              targetRawIndex === endRawIndex || targetPenIndex === segment.endPenIndex
                ? `该K线是向${segment.direction === "up" ? "上" : "下"}线段的结束端点。`
                : `该K线位于线段结束拐点相邻共享笔中。按缠论口径，这里与真正取作端点的那根K线属于同一个共享拐点。`,
          }
        : {
            type: "none",
            segmentDirection: segment.direction,
            penIndex: segment.endPenIndex,
            pivotRawIndex: endRawIndex,
            explanation:
              targetRawIndex === endRawIndex || targetPenIndex === segment.endPenIndex
                ? `该K线是当前未确认向${segment.direction === "up" ? "上" : "下"}线段的临时终点。它只是活动线段暂时延伸到这里，还不是已确认端点。`
                : `该K线位于当前未确认向${segment.direction === "up" ? "上" : "下"}线段临时终点相邻共享笔中。它对应的是同一个候选拐点，而不是普通内部K线。`,
          };
    }
  }

  const activeSegmentIndex = segments.findIndex((segment) => !segment.confirmed);
  if (activeSegmentIndex > 0) {
    const activeSegment = segments[activeSegmentIndex];
    const prevConfirmedSegment = segments[activeSegmentIndex - 1];
    const candidatePenIndices = new Set<number>(
      [
        activeSegment.startPenIndex,
        activeSegment.startPenIndex - 1,
        prevConfirmedSegment.endPenIndex,
        prevConfirmedSegment.endPenIndex - 1,
      ].filter((value) => value >= 0)
    );

    if (candidatePenIndices.has(targetPenIndex)) {
      return {
        type: "endpoint",
        isEndpoint: true,
        segmentDirection: activeSegment.direction,
        penIndex: targetPenIndex,
        pivotRawIndex: pens[activeSegment.startPenIndex]?.startRawIndex,
        finishMode:
          prevConfirmedSegment.finishMode === "active" ? undefined : prevConfirmedSegment.finishMode,
        explanation: `该K线命中了当前未确认向${activeSegment.direction === "up" ? "上" : "下"}线段的起始共享拐点。这个位置同时也是前一向${prevConfirmedSegment.direction === "up" ? "上" : "下"}已确认线段的结束端点，因此这里应视为有效端点，而不是普通内部K线。`,
      };
    }
  }

  return null;
}

export function diagnoseFractal(
  data: KlineData[],
  targetTimestamp: number,
  targetTime?: string,
  startDate?: string
): FractalDiagnosis {
  if (!data || data.length < 7) {
    return { type: "none", explanation: "数据不足，无法进行分型诊断。" };
  }

  const rawBars: RawBar[] = data.map((bar, rawIndex) => ({ ...bar, rawIndex }));
  const normalizedTargetTime = typeof targetTime === "string" ? targetTime.trim() : "";
  const targetBar =
    rawBars.find((bar) => bar.timestamp === targetTimestamp) ??
    (normalizedTargetTime
      ? rawBars.find((bar) => (bar.time || "").trim() === normalizedTargetTime)
      : undefined) ??
    rawBars.reduce<RawBar | null>((best, current) => {
      const distance = Math.abs(current.timestamp - targetTimestamp);
      if (distance > 5 * 60) {
        return best;
      }
      if (!best) {
        return current;
      }
      return Math.abs(best.timestamp - targetTimestamp) <= distance ? best : current;
    }, null);

  if (!targetBar) {
    return {
      type: "none",
      explanation: "没有找到对应的目标K线。通常有两种原因：一是双击时间与原始K线时间存在轻微偏差；二是该日期附近的历史K线还没有被前端加载。若这是较早历史，请先向左拖动主图，把那段K线加载出来后再诊断。",
    };
  }

  let filteredRawBars = rawBars;
  if (startDate) {
    filteredRawBars = rawBars.filter((item) => getBarTradingDate(item) >= startDate);
  }

  if (filteredRawBars.length === 0) {
    return { type: "none", explanation: "选定起始日期后无有效数据。" };
  }

  if (startDate && getBarTradingDate(targetBar) < startDate) {
    return {
      type: "none",
      explanation: `这根K线早于当前画线起始日期 ${startDate}，因此不参与当前自动画线与分型计算。`,
    };
  }

  const normalizedFilteredRawBars: RawBar[] = filteredRawBars.map((bar, rawIndex) => ({
    ...bar,
    rawIndex,
  }));
  const normalizedTargetRawIndex = normalizedFilteredRawBars.findIndex(
    (bar) => bar.timestamp === targetBar.timestamp
  );
  if (normalizedTargetRawIndex < 0) {
    return {
      type: "none",
      explanation: "目标K线当前不在起始日期过滤后的计算范围内，请确认起始日期与已加载历史数据范围。",
    };
  }

  const standardBars = buildStandardBars(normalizedFilteredRawBars);
  const allFractals = detectFractals(standardBars, normalizedFilteredRawBars);
  const compressedFractals = compressFractals(allFractals);
  const pens = buildPens(compressedFractals, normalizedFilteredRawBars);
  const effectiveFractalIndices = getEffectiveFractalIndicesFromPens(pens);

  for (const f of compressedFractals) {
    if (!effectiveFractalIndices.has(f.index)) {
      continue;
    }

    const located = locateFractalElement(standardBars, f, normalizedTargetRawIndex);
    if (!located) {
      continue;
    }

    if (located.elementRole === "second") {
      return {
        type: f.type,
        elementRole: "second",
        isExtreme: located.isExtreme,
        explanation: `该K线属于${f.type === "top" ? "顶" : "底"}分型的第二根元素（核心K线）。${
          located.isExtreme ? `它就是该分型真正的${f.type === "top" ? "最高" : "最低"}点。` : "它位于第二元素内部，但不是该分型最终取用的极值原始K线。"
        }分型价格为${f.price}。`,
      };
    }

    return {
      type: f.type,
      elementRole: located.elementRole,
      explanation: `该K线属于${f.type === "top" ? "顶" : "底"}分型的${located.elementRole === "first" ? "第一" : "第三"}根元素（${located.elementRole === "first" ? "左侧" : "右侧"}确认K线）。分型价格为${f.price}。`,
    };
  }

  for (const f of compressedFractals) {
    if (effectiveFractalIndices.has(f.index)) {
      continue;
    }

    const located = locateFractalElement(standardBars, f, normalizedTargetRawIndex);
    if (!located) {
      continue;
    }

    return {
      type: "none",
      explanation: `该K线曾落在一个${f.type === "top" ? "顶" : "底"}分型候选结构的第${located.elementRole === "first" ? "一" : located.elementRole === "second" ? "二" : "三"}元素中。它虽然通过了单个分型判定，但没有成为最终有效成笔拐点，通常是因为后面出现了更强的同类分型，或者该位置只是笔内中继结构，最终被取舍规则作废。`,
    };
  }

  const compressedFractalStdIndices = new Set(compressedFractals.map((f) => f.stdBarIndex));
  for (const f of allFractals) {
    if (compressedFractalStdIndices.has(f.stdBarIndex)) {
      continue;
    }

    const located = locateFractalElement(standardBars, f, normalizedTargetRawIndex);
    if (!located) {
      continue;
    }

    return {
      type: "none",
      explanation: `该K线曾落在一个${f.type === "top" ? "顶" : "底"}分型候选结构的第${located.elementRole === "first" ? "一" : located.elementRole === "second" ? "二" : "三"}元素中，但这个候选分型后来没有进入有效分型序列。原因通常是后面出现了更强的同类分型，或者该分型只是中继分型，最终被取舍规则作废。`,
    };
  }

  for (const p of pens) {
    if (normalizedTargetRawIndex >= p.startRawIndex && normalizedTargetRawIndex <= p.endRawIndex) {
      return {
        type: "none",
        explanation: `该K线不属于任何分型组成，它是从${p.startPrice}到${p.endPrice}的向${
          p.direction === "up" ? "上" : "下"
        }一笔的一部分。`,
      };
    }
  }

  return {
    type: "none",
    explanation: "该K线目前不属于任何已识别的分型或笔结构。",
  };
}

export function diagnoseSegmentEndpoint(
  data: KlineData[],
  targetTimestamp: number,
  targetTime?: string,
  startDate?: string
): SegmentEndpointDiagnosis {
  if (!data || data.length < 7) {
    return { type: "none", explanation: "数据不足，无法进行线段端点诊断。" };
  }

  const rawBars: RawBar[] = data.map((bar, rawIndex) => ({ ...bar, rawIndex }));
  const normalizedTargetTime = typeof targetTime === "string" ? targetTime.trim() : "";
  const targetBar =
    rawBars.find((bar) => bar.timestamp === targetTimestamp) ??
    (normalizedTargetTime
      ? rawBars.find((bar) => (bar.time || "").trim() === normalizedTargetTime)
      : undefined) ??
    rawBars.reduce<RawBar | null>((best, current) => {
      const distance = Math.abs(current.timestamp - targetTimestamp);
      if (distance > 5 * 60) {
        return best;
      }
      if (!best) {
        return current;
      }
      return Math.abs(best.timestamp - targetTimestamp) <= distance ? best : current;
    }, null);

  if (!targetBar) {
    return {
      type: "none",
      explanation: "没有找到对应的目标K线，请确认双击位置时间与当前已加载历史范围。",
    };
  }

  let filteredRawBars = rawBars;
  if (startDate) {
    filteredRawBars = rawBars.filter((item) => getBarTradingDate(item) >= startDate);
  }

  if (filteredRawBars.length === 0) {
    return { type: "none", explanation: "选定起始日期后无有效数据。" };
  }

  if (startDate && getBarTradingDate(targetBar) < startDate) {
    return {
      type: "none",
      explanation: `这根K线早于当前画线起始日期 ${startDate}，因此不参与当前自动画线与线段端点计算。`,
    };
  }

  const normalizedFilteredRawBars: RawBar[] = filteredRawBars.map((bar, rawIndex) => ({
    ...bar,
    rawIndex,
  }));
  const normalizedTargetRawIndex = normalizedFilteredRawBars.findIndex(
    (bar) => bar.timestamp === targetBar.timestamp
  );
  if (normalizedTargetRawIndex < 0) {
    return {
      type: "none",
      explanation: "目标K线当前不在起始日期过滤后的计算范围内，请确认起始日期与已加载历史数据范围。",
    };
  }

  const standardBars = buildStandardBars(normalizedFilteredRawBars);
  const fractals = compressFractals(detectFractals(standardBars, normalizedFilteredRawBars));
  const pens = buildPens(fractals, normalizedFilteredRawBars);
  const segments = buildSegments(pens);
  const targetPenIndex = locateTargetPenIndex(pens, normalizedTargetRawIndex);

  if (targetPenIndex < 0) {
    return {
      type: "none",
      explanation: "该K线目前不在任何已确认笔内，因此也不可能是已识别线段的端点。",
    };
  }

  const directEndpointMatch = findSegmentEndpointMatch(
    pens,
    segments,
    normalizedTargetRawIndex,
    targetPenIndex
  );
  if (directEndpointMatch) {
    return directEndpointMatch;
  }

  const diagnosis = buildSegmentEndpointDiagnosis(
    pens,
    normalizedTargetRawIndex,
    targetPenIndex
  );
  if (diagnosis) {
    return diagnosis;
  }

  const activeSegment = [...segments].reverse().find((segment) => !segment.confirmed);
  if (activeSegment) {
    for (let i = activeSegment.startPenIndex; i <= activeSegment.endPenIndex; i += 1) {
      const pen = pens[i];
      if (!pen) {
        continue;
      }
      const start = Math.min(pen.startRawIndex, pen.endRawIndex);
      const end = Math.max(pen.startRawIndex, pen.endRawIndex);
      if (normalizedTargetRawIndex < start || normalizedTargetRawIndex > end) {
        continue;
      }

      const isActiveTail = normalizedTargetRawIndex === activeSegment.endRawIndex;
      return {
        type: "none",
        segmentDirection: activeSegment.direction,
        penIndex: i,
        explanation: isActiveTail
          ? `该K线是当前未确认向${activeSegment.direction === "up" ? "上" : "下"}线段的临时终点。它只是活动线段暂时延伸到这里，还不是已确认端点。按缠论口径，向上线段最终必须由顶分型结束，向下线段最终必须由底分型结束；在新的特征序列确认前，这里都不能当作正式端点。`
          : `该K线位于当前未确认向${activeSegment.direction === "up" ? "上" : "下"}线段内部。当前这段线段还在延伸中，因此这根K线不是已确认端点。`,
      };
    }
  }

  return {
    type: "none",
    explanation: `该K线位于第${targetPenIndex + 1}笔中，但当前既不是已确认线段端点，也不是正在被校验的候选端点核心K线。通常说明它只是线段内部普通K线。`,
  };
}

export function buildChanAutoDrawResult(data: KlineData[]): ChanAutoDrawResult {
  if (!data || data.length < 7) {
    return { pens: [], segments: [], lines: [] };
  }

  const rawBars: RawBar[] = data.map((bar, rawIndex) => ({ ...bar, rawIndex }));
  const standardBars = buildStandardBars(rawBars);
  const fractals = compressFractals(detectFractals(standardBars, rawBars));
  const pens = buildPens(fractals, rawBars);
  const segments = buildSegments(pens);
  const latestBar = rawBars[rawBars.length - 1];

  const lines: AutoDrawLine[] = [
    ...pens.map((pen) => ({
      id: `pen-${pen.index}`,
      kind: "pen" as const,
      direction: pen.direction,
      startTimestamp: pen.startTimestamp,
      startPrice: pen.startPrice,
      endTimestamp: pen.endTimestamp,
      endPrice: pen.endPrice,
      confirmed: pen.confirmed,
    })),
    ...segments.map((segment) => ({
      id: `segment-${segment.index}`,
      kind: "segment" as const,
      direction: segment.direction,
      startTimestamp: segment.startTimestamp,
      startPrice: segment.startPrice,
      endTimestamp: segment.endTimestamp,
      endPrice: segment.endPrice,
      confirmed: segment.confirmed,
      finishMode: segment.finishMode,
    })),
  ];

  const lastPen = pens[pens.length - 1];
  if (lastPen && latestBar.timestamp > lastPen.endTimestamp) {
    const direction: Direction = lastPen.direction === "up" ? "down" : "up";
    lines.push({
      id: `pen-active-${latestBar.rawIndex}`,
      kind: "pen",
      direction,
      startTimestamp: lastPen.endTimestamp,
      startPrice: lastPen.endPrice,
      endTimestamp: latestBar.timestamp,
      endPrice: direction === "up" ? latestBar.high : latestBar.low,
      confirmed: false,
    });
  }

  return { pens, segments, lines };
}
