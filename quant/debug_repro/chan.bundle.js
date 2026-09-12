// frontend/src/lib/chan.ts
var RELAXED_PEN_MIN_GAP = 3;
function getBarTradingDate(bar) {
  const timeText = typeof bar.time === "string" ? bar.time.trim() : "";
  const matched = timeText.match(/^(\d{4}-\d{2}-\d{2})/);
  if (matched) {
    return matched[1];
  }
  const date = new Date(bar.timestamp * 1e3);
  const yyyy = String(date.getFullYear());
  const mm = String(date.getMonth() + 1).padStart(2, "0");
  const dd = String(date.getDate()).padStart(2, "0");
  return `${yyyy}-${mm}-${dd}`;
}
function hasInclusion(a, b) {
  return a.high >= b.high && a.low <= b.low || a.high <= b.high && a.low >= b.low;
}
function inferDirection(previous, next, lastDirection) {
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
function mergeStandardBars(a, b, direction) {
  if (direction === "up") {
    return {
      index: a.index,
      high: Math.max(a.high, b.high),
      low: Math.max(a.low, b.low),
      rawIndices: [...a.rawIndices, b.rawIndex]
    };
  }
  return {
    index: a.index,
    high: Math.min(a.high, b.high),
    low: Math.min(a.low, b.low),
    rawIndices: [...a.rawIndices, b.rawIndex]
  };
}
function buildStandardBars(rawBars) {
  if (rawBars.length === 0) return [];
  const standardBars = [
    {
      index: 0,
      high: rawBars[0].high,
      low: rawBars[0].low,
      rawIndices: [rawBars[0].rawIndex]
    }
  ];
  let lastDirection = null;
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
      rawIndices: [nextRaw.rawIndex]
    });
  }
  return standardBars;
}
function findCoreRawIndex(stdBar, rawBars, type) {
  let bestIndex = stdBar.rawIndices[0];
  let bestPrice = type === "top" ? Number.NEGATIVE_INFINITY : Number.POSITIVE_INFINITY;
  for (const rawIndex of stdBar.rawIndices) {
    const rawBar = rawBars[rawIndex];
    if (!rawBar) continue;
    const price = type === "top" ? rawBar.high : rawBar.low;
    const isBetter = type === "top" ? price > bestPrice || price === bestPrice && rawIndex > bestIndex : price < bestPrice || price === bestPrice && rawIndex > bestIndex;
    if (isBetter) {
      bestPrice = price;
      bestIndex = rawIndex;
    }
  }
  return bestIndex;
}
function detectFractals(standardBars, rawBars) {
  const fractals = [];
  for (let i = 1; i < standardBars.length - 1; i += 1) {
    const left = standardBars[i - 1];
    const mid = standardBars[i];
    const right = standardBars[i + 1];
    const isTop = mid.high > left.high && mid.high > right.high && mid.low > left.low && mid.low > right.low;
    const isBottom = mid.low < left.low && mid.low < right.low && mid.high < left.high && mid.high < right.high;
    if (!isTop && !isBottom) {
      continue;
    }
    const type = isTop ? "top" : "bottom";
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
      coreRawIndex: findCoreRawIndex(mid, rawBars, type)
    });
  }
  return fractals;
}
function pickStrongerFractal(a, b) {
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
function compressFractals(fractals) {
  const result = [];
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
function hasOverlap(aStart, aEnd, bStart, bEnd) {
  return Math.max(aStart, bStart) <= Math.min(aEnd, bEnd);
}
function isValidPen(start, end) {
  if (start.type === end.type) return false;
  if (hasOverlap(start.rawStart, start.rawEnd, end.rawStart, end.rawEnd)) return false;
  if (start.type === "top" && end.rangeLow > start.rangeHigh) return false;
  if (start.type === "bottom" && end.rangeHigh < start.rangeLow) return false;
  return Math.abs(end.coreRawIndex - start.coreRawIndex) - 1 >= RELAXED_PEN_MIN_GAP;
}
function makePen(start, end, rawBars, index) {
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
    confirmed: true
  };
}
function normalizePenConnections(pens) {
  if (pens.length === 0) {
    return [];
  }
  const normalized = [{ ...pens[0], index: 0 }];
  for (let i = 1; i < pens.length; i += 1) {
    const current = { ...pens[i], index: normalized.length };
    const prev = normalized[normalized.length - 1];
    if (current.startRawIndex !== prev.endRawIndex || current.startPrice !== prev.endPrice || current.startTimestamp !== prev.endTimestamp) {
      prev.endFractalIndex = current.startFractalIndex;
      prev.endPrice = current.startPrice;
      prev.endRawIndex = current.startRawIndex;
      prev.endTimestamp = current.startTimestamp;
    }
    normalized.push(current);
  }
  return normalized;
}
function mergeSameDirectionPens(pens) {
  if (pens.length <= 1) {
    return pens;
  }
  const merged = [];
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
      confirmed: last.confirmed && pen.confirmed
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
      startTimestamp: prev.endTimestamp
    };
  });
}
function buildPens(fractals, rawBars) {
  if (fractals.length < 2) return [];
  const pens = [];
  let start = fractals[0];
  let endCandidate = null;
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
    const startInvalidated = start.type === "top" ? current.price > start.price : current.price < start.price;
    if (startInvalidated) {
      start = current;
      endCandidate = null;
      continue;
    }
    pens.push(makePen(start, endCandidate, rawBars, pens.length));
    start = endCandidate;
    endCandidate = isValidPen(start, current) ? current : null;
  }
  return mergeSameDirectionPens(normalizePenConnections(pens));
}
function getPenHigh(pen) {
  return Math.max(pen.startPrice, pen.endPrice);
}
function getPenLow(pen) {
  return Math.min(pen.startPrice, pen.endPrice);
}
function hasThreePenOverlap(pens) {
  if (pens.length < 3) return false;
  const lows = pens.map((pen) => getPenLow(pen));
  const highs = pens.map((pen) => getPenHigh(pen));
  return Math.max(...lows) <= Math.min(...highs);
}
function trySeedSegment(pens, startIndex) {
  if (startIndex + 2 >= pens.length) return null;
  const window = pens.slice(startIndex, startIndex + 3);
  if (window[0].direction !== window[2].direction) return null;
  if (window[0].direction === window[1].direction) return null;
  if (!hasThreePenOverlap(window)) return null;
  return {
    direction: window[0].direction,
    startPenIndex: startIndex,
    endPenIndex: startIndex + 2,
    penIndices: [startIndex, startIndex + 1, startIndex + 2]
  };
}
function buildFeatureSequence(pens, segmentDirection, startPenIndex, endPenIndex, featureDirection) {
  const result = [];
  for (let i = startPenIndex; i <= endPenIndex; i += 1) {
    const pen = pens[i];
    if (!pen || pen.direction !== featureDirection) continue;
    result.push({
      index: result.length,
      penIndex: i,
      high: getPenHigh(pen),
      low: getPenLow(pen)
    });
  }
  if (segmentDirection === "up" || segmentDirection === "down") {
    return result;
  }
  return result;
}
function normalizeFeatureSequence(elements, options) {
  if (elements.length === 0) return [];
  const preserveLeadingPair = options?.preserveLeadingPair === true;
  if (preserveLeadingPair && elements.length >= 2) {
    const result2 = [
      {
        index: 0,
        high: elements[0].high,
        low: elements[0].low,
        sourcePenIndices: [elements[0].penIndex]
      },
      {
        index: 1,
        high: elements[1].high,
        low: elements[1].low,
        sourcePenIndices: [elements[1].penIndex]
      }
    ];
    let lastDirection2 = inferDirection(elements[0], elements[1], null);
    for (let i = 2; i < elements.length; i += 1) {
      const next = elements[i];
      const last = result2[result2.length - 1];
      if (hasInclusion(last, next)) {
        const direction = inferDirection(last, next, lastDirection2);
        result2[result2.length - 1] = direction === "up" ? {
          index: last.index,
          high: Math.max(last.high, next.high),
          low: Math.max(last.low, next.low),
          sourcePenIndices: [...last.sourcePenIndices, next.penIndex]
        } : {
          index: last.index,
          high: Math.min(last.high, next.high),
          low: Math.min(last.low, next.low),
          sourcePenIndices: [...last.sourcePenIndices, next.penIndex]
        };
        lastDirection2 = direction;
        continue;
      }
      lastDirection2 = inferDirection(last, next, lastDirection2);
      result2.push({
        index: result2.length,
        high: next.high,
        low: next.low,
        sourcePenIndices: [next.penIndex]
      });
    }
    return result2;
  }
  const result = [
    {
      index: 0,
      high: elements[0].high,
      low: elements[0].low,
      sourcePenIndices: [elements[0].penIndex]
    }
  ];
  let lastDirection = null;
  for (let i = 1; i < elements.length; i += 1) {
    const next = elements[i];
    const last = result[result.length - 1];
    if (hasInclusion(last, next)) {
      const direction = inferDirection(last, next, lastDirection);
      result[result.length - 1] = direction === "up" ? {
        index: last.index,
        high: Math.max(last.high, next.high),
        low: Math.max(last.low, next.low),
        sourcePenIndices: [...last.sourcePenIndices, next.penIndex]
      } : {
        index: last.index,
        high: Math.min(last.high, next.high),
        low: Math.min(last.low, next.low),
        sourcePenIndices: [...last.sourcePenIndices, next.penIndex]
      };
      lastDirection = direction;
      continue;
    }
    lastDirection = inferDirection(last, next, lastDirection);
    result.push({
      index: result.length,
      high: next.high,
      low: next.low,
      sourcePenIndices: [next.penIndex]
    });
  }
  return result;
}
function detectFeatureFractal(normalized, requiredType, strict = false, afterSourcePenIndex = -1) {
  for (let i = 1; i < normalized.length - 1; i += 1) {
    const left = normalized[i - 1];
    const mid = normalized[i];
    const right = normalized[i + 1];
    const isTop = strict ? mid.high > left.high && mid.high > right.high && mid.low > left.low && mid.low > right.low : mid.high > left.high && mid.high > right.high;
    const isBottom = strict ? mid.low < left.low && mid.low < right.low && mid.high < left.high && mid.high < right.high : mid.low < left.low && mid.low < right.low;
    if (requiredType === "top" && !isTop || requiredType === "bottom" && !isBottom) {
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
      sourcePenIndices: [...left.sourcePenIndices, ...mid.sourcePenIndices, ...right.sourcePenIndices]
    };
  }
  return null;
}
function makeFeatureSequenceAnalysis(sequenceKind, pens, segmentDirection, startPenIndex, endPenIndex, featureDirection, requiredType, options) {
  const elements = buildFeatureSequence(
    pens,
    segmentDirection,
    startPenIndex,
    endPenIndex,
    featureDirection
  );
  const normalizedElements = normalizeFeatureSequence(elements, {
    preserveLeadingPair: true,
    ...options
  });
  return {
    sequenceKind,
    segmentDirection,
    featureDirection,
    elements,
    normalizedElements,
    fractal: detectFeatureFractal(normalizedElements, requiredType)
  };
}
function isBasicSegmentPivotCandidate(pens, pivotPenIndex, segmentDirection) {
  const pivotPen = pens[pivotPenIndex];
  const prevPen = pens[pivotPenIndex - 1];
  const boundaryPenDirection = segmentDirection === "up" ? "down" : "up";
  if (!pivotPen || !prevPen) {
    return false;
  }
  if (pivotPen.direction !== boundaryPenDirection) {
    return false;
  }
  if (prevPen.direction === pivotPen.direction) {
    return false;
  }
  return pivotPen.startRawIndex === prevPen.endRawIndex && pivotPen.startTimestamp === prevPen.endTimestamp;
}
function resolveSegmentBoundaryPenIndex(pens, startPenIndex, searchEndPenIndex, segmentDirection, candidatePenIndices, fallbackMidPenIndex, fallbackPrice) {
  const boundaryPenDirection = segmentDirection === "up" ? "down" : "up";
  let bestPenIndex = -1;
  let bestPrice = segmentDirection === "up" ? Number.NEGATIVE_INFINITY : Number.POSITIVE_INFINITY;
  const allowedPenIndices = candidatePenIndices ? new Set(candidatePenIndices) : null;
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
    const better = segmentDirection === "up" ? pen.startPrice > bestPrice : pen.startPrice < bestPrice;
    const samePriceEarlier = pen.startPrice === bestPrice && i < bestPenIndex;
    if (better || samePriceEarlier) {
      bestPenIndex = i;
      bestPrice = pen.startPrice;
    }
  }
  if (bestPenIndex < 0) {
    for (let i = startPenIndex + 1; i <= searchEndPenIndex; i += 1) {
      if (allowedPenIndices && !allowedPenIndices.has(i)) {
        continue;
      }
      const pen = pens[i];
      if (!pen || pen.direction !== boundaryPenDirection) {
        continue;
      }
      const better = segmentDirection === "up" ? pen.startPrice > bestPrice : pen.startPrice < bestPrice;
      const samePriceEarlier = pen.startPrice === bestPrice && i < bestPenIndex;
      if (better || samePriceEarlier) {
        bestPenIndex = i;
        bestPrice = pen.startPrice;
      }
    }
  }
  if (bestPenIndex < 0 && fallbackMidPenIndex !== void 0 && fallbackPrice !== void 0) {
    bestPenIndex = fallbackMidPenIndex;
    bestPrice = fallbackPrice;
  }
  return {
    finishPenIndex: bestPenIndex,
    finishPrice: bestPrice
  };
}
function expandFeatureFractalPenRange(sourcePenIndices) {
  if (sourcePenIndices.length === 0) {
    return [];
  }
  const minPenIndex = Math.min(...sourcePenIndices);
  const maxPenIndex = Math.max(...sourcePenIndices);
  return Array.from({ length: maxPenIndex - minPenIndex + 1 }, (_, offset) => minPenIndex + offset);
}
function analyzeSegmentFinish(pens, startPenIndex, endPenIndex, segmentDirection, afterSourcePenIndex = -1) {
  const segmentStartPrice = pens[startPenIndex]?.startPrice ?? NaN;
  const isBoundaryDirectionValid = (finishPrice) => segmentDirection === "up" ? finishPrice > segmentStartPrice : finishPrice < segmentStartPrice;
  const primaryFeatureDirection = segmentDirection === "up" ? "down" : "up";
  const primaryRequiredType = segmentDirection === "up" ? "top" : "bottom";
  const normalizationStrategies = [
    {},
    { preserveLeadingPair: true },
    { noNormalize: true }
  ];
  let primary = null;
  for (const strategy of normalizationStrategies) {
    const elements = buildFeatureSequence(
      pens,
      segmentDirection,
      startPenIndex,
      endPenIndex,
      primaryFeatureDirection
    );
    let normalizedElements;
    if (strategy.noNormalize) {
      normalizedElements = elements.map((el) => ({
        index: el.index,
        high: el.high,
        low: el.low,
        sourcePenIndices: [el.penIndex]
      }));
    } else {
      normalizedElements = normalizeFeatureSequence(elements, {
        preserveLeadingPair: strategy.preserveLeadingPair === true
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
        fractal
      };
      break;
    }
  }
  if (!primary || !primary.fractal) {
    return {
      primary: primary ?? makeFeatureSequenceAnalysis(
        "primary",
        pens,
        segmentDirection,
        startPenIndex,
        endPenIndex,
        primaryFeatureDirection,
        primaryRequiredType,
        { preserveLeadingPair: true }
      ),
      secondary: null,
      decision: null
    };
  }
  if (!primary.fractal.hasGapBetween12) {
    const boundary2 = resolveSegmentBoundaryPenIndex(
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
      decision: boundary2.finishPenIndex < 0 || !isBoundaryDirectionValid(boundary2.finishPrice) ? null : {
        confirmed: true,
        finishPenIndex: boundary2.finishPenIndex,
        finishPrice: boundary2.finishPrice,
        finishMode: "case1"
      }
    };
  }
  const secondaryFeatureDirection = segmentDirection;
  const secondaryRequiredType = segmentDirection === "up" ? "bottom" : "top";
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
    decision: !secondary.fractal || boundary.finishPenIndex < 0 || !isBoundaryDirectionValid(boundary.finishPrice) ? null : {
      confirmed: true,
      finishPenIndex: boundary.finishPenIndex,
      finishPrice: boundary.finishPrice,
      finishMode: "case2"
    }
  };
}
function tryConfirmSegmentFinish(pens, startPenIndex, endPenIndex, segmentDirection, afterSourcePenIndex = -1) {
  return analyzeSegmentFinish(pens, startPenIndex, endPenIndex, segmentDirection, afterSourcePenIndex).decision;
}
function makeSegment(pens, index, startPenIndex, endPenIndex, finishMode, confirmed, endPointAt) {
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
    finishMode
  };
}
function findDirectionalExtremePen(pens, startPenIndex, endPenIndex, direction) {
  let bestPenIndex = -1;
  let bestPrice = direction === "up" ? Number.NEGATIVE_INFINITY : Number.POSITIVE_INFINITY;
  for (let i = startPenIndex; i <= endPenIndex; i += 1) {
    const pen2 = pens[i];
    if (!pen2) continue;
    const price = direction === "up" ? getPenHigh(pen2) : getPenLow(pen2);
    const better = direction === "up" ? price > bestPrice : price < bestPrice;
    if (better) {
      bestPrice = price;
      bestPenIndex = i;
    }
  }
  if (bestPenIndex < 0) return null;
  const pen = pens[bestPenIndex];
  const atStart = direction === "up" ? pen.direction === "down" : pen.direction === "up";
  return { penIndex: bestPenIndex, atStart };
}
function checkSegmentFinishDestruction(pens, finish, direction) {
  const oppositeDirection = direction === "up" ? "down" : "up";
  const finishPenIndex = finish.finishPenIndex;
  const finishPrice = finish.finishPrice;
  const oppositeSeedValid = !!trySeedSegment(pens, finishPenIndex);
  for (let k = finishPenIndex + 1; k < pens.length; k += 1) {
    if (oppositeSeedValid) {
      const oppositeFinish = tryConfirmSegmentFinish(pens, finishPenIndex, k, oppositeDirection);
      if (oppositeFinish) {
        return { destroyed: false, breakPenIndex: -1 };
      }
    }
    const pen = pens[k];
    const breaks = direction === "up" ? getPenHigh(pen) > finishPrice : getPenLow(pen) < finishPrice;
    if (breaks) {
      return { destroyed: true, breakPenIndex: k };
    }
  }
  return { destroyed: false, breakPenIndex: -1 };
}
function resolveSegmentFinish(pens, seed) {
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
        afterSourcePenIndex
      };
    }
    afterSourcePenIndex = Math.max(afterSourcePenIndex, destruction.breakPenIndex);
  }
  return { kind: "active", afterSourcePenIndex };
}
function buildSegments(pens) {
  const segments = [];
  let i = 0;
  while (i < pens.length - 2) {
    const seed = trySeedSegment(pens, i);
    if (!seed) {
      i += 1;
      continue;
    }
    const resolved = resolveSegmentFinish(pens, seed);
    if (resolved.kind === "active") {
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
  return segments.filter((segment) => segment.endTimestamp > segment.startTimestamp).map((segment, index) => ({ ...segment, index }));
}
function getEffectiveFractalIndicesFromPens(pens) {
  const indices = /* @__PURE__ */ new Set();
  for (const pen of pens) {
    indices.add(pen.startFractalIndex);
    indices.add(pen.endFractalIndex);
  }
  return indices;
}
function locateFractalElement(standardBars, fractal, targetRawIndex) {
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
      isExtreme: targetRawIndex === fractal.coreRawIndex
    };
  }
  if (rightStd.rawIndices.includes(targetRawIndex)) {
    return { elementRole: "third", isExtreme: false };
  }
  return null;
}
function locateTargetPenIndex(pens, targetRawIndex) {
  return pens.findIndex((pen) => {
    const start = Math.min(pen.startRawIndex, pen.endRawIndex);
    const end = Math.max(pen.startRawIndex, pen.endRawIndex);
    return targetRawIndex >= start && targetRawIndex <= end;
  });
}
function buildSegmentEndpointDiagnosis(pens, targetRawIndex, targetPenIndex) {
  let bestMatch = null;
  let i = 0;
  while (i < pens.length - 2) {
    const seed = trySeedSegment(pens, i);
    if (!seed) {
      i += 1;
      continue;
    }
    const resolved = resolveSegmentFinish(pens, seed);
    if (resolved.kind === "active") {
      break;
    }
    const finishPenIndex = resolved.finishPenIndex;
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
      const upText = analysis.primary.segmentDirection === "up" ? "\u4E0A" : "\u4E0B";
      let explanation;
      if (isEndpoint) {
        explanation = `\u8BE5K\u7EBF\u5C31\u662F\u5411${upText}\u7EBF\u6BB5\u7684\u7AEF\u70B9\u3002\u7EA2\u6846\u91CC\u7684\u7279\u5F81\u5E8F\u5217\u5728\u53BB\u5305\u542B\u540E\u7684\u6807\u51C6\u7279\u5F81\u5E8F\u5217\u4E2D\u5DF2\u7ECF\u5F62\u6210${leftType === "top" ? "\u9876" : "\u5E95"}\u5206\u578B\uFF0C\u56E0\u6B64\u8BE5\u5206\u578B\u8986\u76D6\u533A\u57DF\u91CC\u7684${analysis.primary.segmentDirection === "up" ? "\u6700\u9AD8" : "\u6700\u4F4E"}K\u7EBF\u88AB\u53D6\u4E3A\u62D0\u70B9\u3002${analysis.decision?.finishMode === "case2" ? `\u5F53\u524D\u5C5E\u4E8E\u7B2C\u4E8C\u79CD\u60C5\u51B5\uFF0C\u4E3B\u7279\u5F81\u5E8F\u5217\u5206\u578B\u4E4B\u95F4\u6709\u7F3A\u53E3\uFF0C\u53F3\u4FA7\u7B2C\u4E8C\u7279\u5F81\u5E8F\u5217\u4E5F\u5DF2\u5F62\u6210${rightType === "top" ? "\u9876" : "\u5E95"}\u5206\u578B\uFF0C\u6545\u7AEF\u70B9\u6700\u7EC8\u6210\u7ACB\u3002` : "\u5F53\u524D\u5C5E\u4E8E\u7B2C\u4E00\u79CD\u60C5\u51B5\uFF0C\u4E3B\u7279\u5F81\u5E8F\u5217\u5206\u578B\u6210\u7ACB\u540E\u76F4\u63A5\u786E\u8BA4\u7AEF\u70B9\u3002"}`;
      } else if (inFinishPen) {
        explanation = `\u8BE5K\u7EBF\u4F4D\u4E8E\u7AEF\u70B9\u6240\u5728\u7B14\uFF08\u7B2C${finishPenIndex + 1}\u7B14\uFF09\u5185\uFF0C\u4F46\u5B83\u4E0D\u662F\u7AEF\u70B9\u672C\u8EAB\uFF1B\u771F\u6B63\u88AB\u53D6\u4F5C\u7AEF\u70B9\u7684\u662F\u8FD9\u7B14\u8D77\u70B9\u90A3\u6839K\u7EBF\u3002`;
      } else {
        explanation = `\u8BE5K\u7EBF\u4F4D\u4E8E\u5411${upText}\u7EBF\u6BB5\u5185\u90E8\uFF0C\u4E0D\u662F\u7EBF\u6BB5\u7AEF\u70B9\u3002\u7EBF\u6BB5\u7AEF\u70B9\u53EA\u4F1A\u51FA\u73B0\u5728\u8BE5\u65B9\u5411\u4E0A\u7684\u9876/\u5E95\u5206\u578B\u5904\uFF1B\u5373\u4F7F\u6B64\u5904\u66FE\u5F62\u6210\u8FC7\u7279\u5F81\u5206\u578B\u5019\u9009\uFF0C\u53EA\u8981\u540E\u7EED\u8D70\u52BF\u7834\u574F\u4E86\u5B83\uFF0C\u8FD9\u91CC\u5C31\u4E0D\u662F\u6700\u7EC8\u7AEF\u70B9\u3002`;
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
          _sequenceEndPenIndex: finishPenIndex
        };
      }
    }
    i = finishPenIndex;
  }
  return bestMatch;
}
function findSegmentEndpointMatch(pens, segments, targetRawIndex, targetPenIndex) {
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
    const matchesStartEndpoint = targetRawIndex === startRawIndex || targetPenIndex === segment.startPenIndex || !!prevStartSharedPen && prevStartSharedPen.endRawIndex === startRawIndex && targetPenIndex === segment.startPenIndex - 1;
    const matchesEndEndpoint = targetRawIndex === endRawIndex || targetPenIndex === segment.endPenIndex || !!nextEndSharedPen && nextEndSharedPen.endRawIndex === endRawIndex && targetPenIndex === segment.endPenIndex - 1;
    if (matchesStartEndpoint) {
      const prevSegment = i > 0 ? segments[i - 1] : null;
      return {
        type: "endpoint",
        isEndpoint: true,
        segmentDirection: segment.direction,
        penIndex: segment.startPenIndex,
        pivotRawIndex: startRawIndex,
        finishMode: prevSegment?.finishMode === "active" ? void 0 : prevSegment?.finishMode,
        explanation: prevSegment ? targetRawIndex === startRawIndex || targetPenIndex === segment.startPenIndex ? `\u8BE5K\u7EBF\u662F\u5411${segment.direction === "up" ? "\u4E0A" : "\u4E0B"}\u7EBF\u6BB5\u7684\u8D77\u59CB\u7AEF\u70B9\uFF0C\u540C\u65F6\u4E5F\u662F\u524D\u4E00\u5411${prevSegment.direction === "up" ? "\u4E0A" : "\u4E0B"}\u7EBF\u6BB5\u7684\u7ED3\u675F\u7AEF\u70B9\u3002\u6309\u7F20\u8BBA\u53E3\u5F84\uFF0C\u7EBF\u6BB5\u4EA4\u754C\u5904\u5C31\u662F\u524D\u540E\u4E24\u6BB5\u5171\u4EAB\u7684\u62D0\u70B9\uFF0C\u56E0\u6B64\u8FD9\u91CC\u5C5E\u4E8E\u6709\u6548\u7AEF\u70B9\u3002` : `\u8BE5K\u7EBF\u4F4D\u4E8E\u7EBF\u6BB5\u8D77\u59CB\u62D0\u70B9\u76F8\u90BB\u5171\u4EAB\u7B14\u4E2D\u3002\u6309\u7F20\u8BBA\u53E3\u5F84\uFF0C\u7EBF\u6BB5\u4EA4\u754C\u5904\u662F\u524D\u540E\u4E24\u7B14\u5171\u4EAB\u7684\u540C\u4E00\u4E2A\u62D0\u70B9\uFF0C\u56E0\u6B64\u8FD9\u91CC\u4E5F\u5E94\u89C6\u4E3A\u547D\u4E2D\u4E86\u8BE5\u7AEF\u70B9\u3002` : targetRawIndex === startRawIndex || targetPenIndex === segment.startPenIndex ? `\u8BE5K\u7EBF\u662F\u5F53\u524D\u5DF2\u8BC6\u522B\u7EBF\u6BB5\u5E8F\u5217\u7684\u8D77\u59CB\u7AEF\u70B9\u3002` : `\u8BE5K\u7EBF\u4F4D\u4E8E\u5F53\u524D\u5DF2\u8BC6\u522B\u7EBF\u6BB5\u8D77\u59CB\u62D0\u70B9\u76F8\u90BB\u5171\u4EAB\u7B14\u4E2D\uFF0C\u56E0\u6B64\u8FD9\u91CC\u4E5F\u547D\u4E2D\u4E86\u8BE5\u7AEF\u70B9\u3002`
      };
    }
    if (matchesEndEndpoint) {
      return segment.confirmed ? {
        type: "endpoint",
        isEndpoint: true,
        segmentDirection: segment.direction,
        penIndex: segment.endPenIndex,
        pivotRawIndex: endRawIndex,
        finishMode: segment.finishMode === "active" ? void 0 : segment.finishMode,
        explanation: targetRawIndex === endRawIndex || targetPenIndex === segment.endPenIndex ? `\u8BE5K\u7EBF\u662F\u5411${segment.direction === "up" ? "\u4E0A" : "\u4E0B"}\u7EBF\u6BB5\u7684\u7ED3\u675F\u7AEF\u70B9\u3002` : `\u8BE5K\u7EBF\u4F4D\u4E8E\u7EBF\u6BB5\u7ED3\u675F\u62D0\u70B9\u76F8\u90BB\u5171\u4EAB\u7B14\u4E2D\u3002\u6309\u7F20\u8BBA\u53E3\u5F84\uFF0C\u8FD9\u91CC\u4E0E\u771F\u6B63\u53D6\u4F5C\u7AEF\u70B9\u7684\u90A3\u6839K\u7EBF\u5C5E\u4E8E\u540C\u4E00\u4E2A\u5171\u4EAB\u62D0\u70B9\u3002`
      } : {
        type: "none",
        segmentDirection: segment.direction,
        penIndex: segment.endPenIndex,
        pivotRawIndex: endRawIndex,
        explanation: targetRawIndex === endRawIndex || targetPenIndex === segment.endPenIndex ? `\u8BE5K\u7EBF\u662F\u5F53\u524D\u672A\u786E\u8BA4\u5411${segment.direction === "up" ? "\u4E0A" : "\u4E0B"}\u7EBF\u6BB5\u7684\u4E34\u65F6\u7EC8\u70B9\u3002\u5B83\u53EA\u662F\u6D3B\u52A8\u7EBF\u6BB5\u6682\u65F6\u5EF6\u4F38\u5230\u8FD9\u91CC\uFF0C\u8FD8\u4E0D\u662F\u5DF2\u786E\u8BA4\u7AEF\u70B9\u3002` : `\u8BE5K\u7EBF\u4F4D\u4E8E\u5F53\u524D\u672A\u786E\u8BA4\u5411${segment.direction === "up" ? "\u4E0A" : "\u4E0B"}\u7EBF\u6BB5\u4E34\u65F6\u7EC8\u70B9\u76F8\u90BB\u5171\u4EAB\u7B14\u4E2D\u3002\u5B83\u5BF9\u5E94\u7684\u662F\u540C\u4E00\u4E2A\u5019\u9009\u62D0\u70B9\uFF0C\u800C\u4E0D\u662F\u666E\u901A\u5185\u90E8K\u7EBF\u3002`
      };
    }
  }
  const activeSegmentIndex = segments.findIndex((segment) => !segment.confirmed);
  if (activeSegmentIndex > 0) {
    const activeSegment = segments[activeSegmentIndex];
    const prevConfirmedSegment = segments[activeSegmentIndex - 1];
    const candidatePenIndices = new Set(
      [
        activeSegment.startPenIndex,
        activeSegment.startPenIndex - 1,
        prevConfirmedSegment.endPenIndex,
        prevConfirmedSegment.endPenIndex - 1
      ].filter((value) => value >= 0)
    );
    if (candidatePenIndices.has(targetPenIndex)) {
      return {
        type: "endpoint",
        isEndpoint: true,
        segmentDirection: activeSegment.direction,
        penIndex: targetPenIndex,
        pivotRawIndex: pens[activeSegment.startPenIndex]?.startRawIndex,
        finishMode: prevConfirmedSegment.finishMode === "active" ? void 0 : prevConfirmedSegment.finishMode,
        explanation: `\u8BE5K\u7EBF\u547D\u4E2D\u4E86\u5F53\u524D\u672A\u786E\u8BA4\u5411${activeSegment.direction === "up" ? "\u4E0A" : "\u4E0B"}\u7EBF\u6BB5\u7684\u8D77\u59CB\u5171\u4EAB\u62D0\u70B9\u3002\u8FD9\u4E2A\u4F4D\u7F6E\u540C\u65F6\u4E5F\u662F\u524D\u4E00\u5411${prevConfirmedSegment.direction === "up" ? "\u4E0A" : "\u4E0B"}\u5DF2\u786E\u8BA4\u7EBF\u6BB5\u7684\u7ED3\u675F\u7AEF\u70B9\uFF0C\u56E0\u6B64\u8FD9\u91CC\u5E94\u89C6\u4E3A\u6709\u6548\u7AEF\u70B9\uFF0C\u800C\u4E0D\u662F\u666E\u901A\u5185\u90E8K\u7EBF\u3002`
      };
    }
  }
  return null;
}
function diagnoseFractal(data, targetTimestamp, targetTime, startDate) {
  if (!data || data.length < 7) {
    return { type: "none", explanation: "\u6570\u636E\u4E0D\u8DB3\uFF0C\u65E0\u6CD5\u8FDB\u884C\u5206\u578B\u8BCA\u65AD\u3002" };
  }
  const rawBars = data.map((bar, rawIndex) => ({ ...bar, rawIndex }));
  const normalizedTargetTime = typeof targetTime === "string" ? targetTime.trim() : "";
  const targetBar = rawBars.find((bar) => bar.timestamp === targetTimestamp) ?? (normalizedTargetTime ? rawBars.find((bar) => (bar.time || "").trim() === normalizedTargetTime) : void 0) ?? rawBars.reduce((best, current) => {
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
      explanation: "\u6CA1\u6709\u627E\u5230\u5BF9\u5E94\u7684\u76EE\u6807K\u7EBF\u3002\u901A\u5E38\u6709\u4E24\u79CD\u539F\u56E0\uFF1A\u4E00\u662F\u53CC\u51FB\u65F6\u95F4\u4E0E\u539F\u59CBK\u7EBF\u65F6\u95F4\u5B58\u5728\u8F7B\u5FAE\u504F\u5DEE\uFF1B\u4E8C\u662F\u8BE5\u65E5\u671F\u9644\u8FD1\u7684\u5386\u53F2K\u7EBF\u8FD8\u6CA1\u6709\u88AB\u524D\u7AEF\u52A0\u8F7D\u3002\u82E5\u8FD9\u662F\u8F83\u65E9\u5386\u53F2\uFF0C\u8BF7\u5148\u5411\u5DE6\u62D6\u52A8\u4E3B\u56FE\uFF0C\u628A\u90A3\u6BB5K\u7EBF\u52A0\u8F7D\u51FA\u6765\u540E\u518D\u8BCA\u65AD\u3002"
    };
  }
  let filteredRawBars = rawBars;
  if (startDate) {
    filteredRawBars = rawBars.filter((item) => getBarTradingDate(item) >= startDate);
  }
  if (filteredRawBars.length === 0) {
    return { type: "none", explanation: "\u9009\u5B9A\u8D77\u59CB\u65E5\u671F\u540E\u65E0\u6709\u6548\u6570\u636E\u3002" };
  }
  if (startDate && getBarTradingDate(targetBar) < startDate) {
    return {
      type: "none",
      explanation: `\u8FD9\u6839K\u7EBF\u65E9\u4E8E\u5F53\u524D\u753B\u7EBF\u8D77\u59CB\u65E5\u671F ${startDate}\uFF0C\u56E0\u6B64\u4E0D\u53C2\u4E0E\u5F53\u524D\u81EA\u52A8\u753B\u7EBF\u4E0E\u5206\u578B\u8BA1\u7B97\u3002`
    };
  }
  const normalizedFilteredRawBars = filteredRawBars.map((bar, rawIndex) => ({
    ...bar,
    rawIndex
  }));
  const normalizedTargetRawIndex = normalizedFilteredRawBars.findIndex(
    (bar) => bar.timestamp === targetBar.timestamp
  );
  if (normalizedTargetRawIndex < 0) {
    return {
      type: "none",
      explanation: "\u76EE\u6807K\u7EBF\u5F53\u524D\u4E0D\u5728\u8D77\u59CB\u65E5\u671F\u8FC7\u6EE4\u540E\u7684\u8BA1\u7B97\u8303\u56F4\u5185\uFF0C\u8BF7\u786E\u8BA4\u8D77\u59CB\u65E5\u671F\u4E0E\u5DF2\u52A0\u8F7D\u5386\u53F2\u6570\u636E\u8303\u56F4\u3002"
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
        explanation: `\u8BE5K\u7EBF\u5C5E\u4E8E${f.type === "top" ? "\u9876" : "\u5E95"}\u5206\u578B\u7684\u7B2C\u4E8C\u6839\u5143\u7D20\uFF08\u6838\u5FC3K\u7EBF\uFF09\u3002${located.isExtreme ? `\u5B83\u5C31\u662F\u8BE5\u5206\u578B\u771F\u6B63\u7684${f.type === "top" ? "\u6700\u9AD8" : "\u6700\u4F4E"}\u70B9\u3002` : "\u5B83\u4F4D\u4E8E\u7B2C\u4E8C\u5143\u7D20\u5185\u90E8\uFF0C\u4F46\u4E0D\u662F\u8BE5\u5206\u578B\u6700\u7EC8\u53D6\u7528\u7684\u6781\u503C\u539F\u59CBK\u7EBF\u3002"}\u5206\u578B\u4EF7\u683C\u4E3A${f.price}\u3002`
      };
    }
    return {
      type: f.type,
      elementRole: located.elementRole,
      explanation: `\u8BE5K\u7EBF\u5C5E\u4E8E${f.type === "top" ? "\u9876" : "\u5E95"}\u5206\u578B\u7684${located.elementRole === "first" ? "\u7B2C\u4E00" : "\u7B2C\u4E09"}\u6839\u5143\u7D20\uFF08${located.elementRole === "first" ? "\u5DE6\u4FA7" : "\u53F3\u4FA7"}\u786E\u8BA4K\u7EBF\uFF09\u3002\u5206\u578B\u4EF7\u683C\u4E3A${f.price}\u3002`
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
      explanation: `\u8BE5K\u7EBF\u66FE\u843D\u5728\u4E00\u4E2A${f.type === "top" ? "\u9876" : "\u5E95"}\u5206\u578B\u5019\u9009\u7ED3\u6784\u7684\u7B2C${located.elementRole === "first" ? "\u4E00" : located.elementRole === "second" ? "\u4E8C" : "\u4E09"}\u5143\u7D20\u4E2D\u3002\u5B83\u867D\u7136\u901A\u8FC7\u4E86\u5355\u4E2A\u5206\u578B\u5224\u5B9A\uFF0C\u4F46\u6CA1\u6709\u6210\u4E3A\u6700\u7EC8\u6709\u6548\u6210\u7B14\u62D0\u70B9\uFF0C\u901A\u5E38\u662F\u56E0\u4E3A\u540E\u9762\u51FA\u73B0\u4E86\u66F4\u5F3A\u7684\u540C\u7C7B\u5206\u578B\uFF0C\u6216\u8005\u8BE5\u4F4D\u7F6E\u53EA\u662F\u7B14\u5185\u4E2D\u7EE7\u7ED3\u6784\uFF0C\u6700\u7EC8\u88AB\u53D6\u820D\u89C4\u5219\u4F5C\u5E9F\u3002`
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
      explanation: `\u8BE5K\u7EBF\u66FE\u843D\u5728\u4E00\u4E2A${f.type === "top" ? "\u9876" : "\u5E95"}\u5206\u578B\u5019\u9009\u7ED3\u6784\u7684\u7B2C${located.elementRole === "first" ? "\u4E00" : located.elementRole === "second" ? "\u4E8C" : "\u4E09"}\u5143\u7D20\u4E2D\uFF0C\u4F46\u8FD9\u4E2A\u5019\u9009\u5206\u578B\u540E\u6765\u6CA1\u6709\u8FDB\u5165\u6709\u6548\u5206\u578B\u5E8F\u5217\u3002\u539F\u56E0\u901A\u5E38\u662F\u540E\u9762\u51FA\u73B0\u4E86\u66F4\u5F3A\u7684\u540C\u7C7B\u5206\u578B\uFF0C\u6216\u8005\u8BE5\u5206\u578B\u53EA\u662F\u4E2D\u7EE7\u5206\u578B\uFF0C\u6700\u7EC8\u88AB\u53D6\u820D\u89C4\u5219\u4F5C\u5E9F\u3002`
    };
  }
  for (const p of pens) {
    if (normalizedTargetRawIndex >= p.startRawIndex && normalizedTargetRawIndex <= p.endRawIndex) {
      return {
        type: "none",
        explanation: `\u8BE5K\u7EBF\u4E0D\u5C5E\u4E8E\u4EFB\u4F55\u5206\u578B\u7EC4\u6210\uFF0C\u5B83\u662F\u4ECE${p.startPrice}\u5230${p.endPrice}\u7684\u5411${p.direction === "up" ? "\u4E0A" : "\u4E0B"}\u4E00\u7B14\u7684\u4E00\u90E8\u5206\u3002`
      };
    }
  }
  return {
    type: "none",
    explanation: "\u8BE5K\u7EBF\u76EE\u524D\u4E0D\u5C5E\u4E8E\u4EFB\u4F55\u5DF2\u8BC6\u522B\u7684\u5206\u578B\u6216\u7B14\u7ED3\u6784\u3002"
  };
}
function diagnoseSegmentEndpoint(data, targetTimestamp, targetTime, startDate) {
  if (!data || data.length < 7) {
    return { type: "none", explanation: "\u6570\u636E\u4E0D\u8DB3\uFF0C\u65E0\u6CD5\u8FDB\u884C\u7EBF\u6BB5\u7AEF\u70B9\u8BCA\u65AD\u3002" };
  }
  const rawBars = data.map((bar, rawIndex) => ({ ...bar, rawIndex }));
  const normalizedTargetTime = typeof targetTime === "string" ? targetTime.trim() : "";
  const targetBar = rawBars.find((bar) => bar.timestamp === targetTimestamp) ?? (normalizedTargetTime ? rawBars.find((bar) => (bar.time || "").trim() === normalizedTargetTime) : void 0) ?? rawBars.reduce((best, current) => {
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
      explanation: "\u6CA1\u6709\u627E\u5230\u5BF9\u5E94\u7684\u76EE\u6807K\u7EBF\uFF0C\u8BF7\u786E\u8BA4\u53CC\u51FB\u4F4D\u7F6E\u65F6\u95F4\u4E0E\u5F53\u524D\u5DF2\u52A0\u8F7D\u5386\u53F2\u8303\u56F4\u3002"
    };
  }
  let filteredRawBars = rawBars;
  if (startDate) {
    filteredRawBars = rawBars.filter((item) => getBarTradingDate(item) >= startDate);
  }
  if (filteredRawBars.length === 0) {
    return { type: "none", explanation: "\u9009\u5B9A\u8D77\u59CB\u65E5\u671F\u540E\u65E0\u6709\u6548\u6570\u636E\u3002" };
  }
  if (startDate && getBarTradingDate(targetBar) < startDate) {
    return {
      type: "none",
      explanation: `\u8FD9\u6839K\u7EBF\u65E9\u4E8E\u5F53\u524D\u753B\u7EBF\u8D77\u59CB\u65E5\u671F ${startDate}\uFF0C\u56E0\u6B64\u4E0D\u53C2\u4E0E\u5F53\u524D\u81EA\u52A8\u753B\u7EBF\u4E0E\u7EBF\u6BB5\u7AEF\u70B9\u8BA1\u7B97\u3002`
    };
  }
  const normalizedFilteredRawBars = filteredRawBars.map((bar, rawIndex) => ({
    ...bar,
    rawIndex
  }));
  const normalizedTargetRawIndex = normalizedFilteredRawBars.findIndex(
    (bar) => bar.timestamp === targetBar.timestamp
  );
  if (normalizedTargetRawIndex < 0) {
    return {
      type: "none",
      explanation: "\u76EE\u6807K\u7EBF\u5F53\u524D\u4E0D\u5728\u8D77\u59CB\u65E5\u671F\u8FC7\u6EE4\u540E\u7684\u8BA1\u7B97\u8303\u56F4\u5185\uFF0C\u8BF7\u786E\u8BA4\u8D77\u59CB\u65E5\u671F\u4E0E\u5DF2\u52A0\u8F7D\u5386\u53F2\u6570\u636E\u8303\u56F4\u3002"
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
      explanation: "\u8BE5K\u7EBF\u76EE\u524D\u4E0D\u5728\u4EFB\u4F55\u5DF2\u786E\u8BA4\u7B14\u5185\uFF0C\u56E0\u6B64\u4E5F\u4E0D\u53EF\u80FD\u662F\u5DF2\u8BC6\u522B\u7EBF\u6BB5\u7684\u7AEF\u70B9\u3002"
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
        explanation: isActiveTail ? `\u8BE5K\u7EBF\u662F\u5F53\u524D\u672A\u786E\u8BA4\u5411${activeSegment.direction === "up" ? "\u4E0A" : "\u4E0B"}\u7EBF\u6BB5\u7684\u4E34\u65F6\u7EC8\u70B9\u3002\u5B83\u53EA\u662F\u6D3B\u52A8\u7EBF\u6BB5\u6682\u65F6\u5EF6\u4F38\u5230\u8FD9\u91CC\uFF0C\u8FD8\u4E0D\u662F\u5DF2\u786E\u8BA4\u7AEF\u70B9\u3002\u6309\u7F20\u8BBA\u53E3\u5F84\uFF0C\u5411\u4E0A\u7EBF\u6BB5\u6700\u7EC8\u5FC5\u987B\u7531\u9876\u5206\u578B\u7ED3\u675F\uFF0C\u5411\u4E0B\u7EBF\u6BB5\u6700\u7EC8\u5FC5\u987B\u7531\u5E95\u5206\u578B\u7ED3\u675F\uFF1B\u5728\u65B0\u7684\u7279\u5F81\u5E8F\u5217\u786E\u8BA4\u524D\uFF0C\u8FD9\u91CC\u90FD\u4E0D\u80FD\u5F53\u4F5C\u6B63\u5F0F\u7AEF\u70B9\u3002` : `\u8BE5K\u7EBF\u4F4D\u4E8E\u5F53\u524D\u672A\u786E\u8BA4\u5411${activeSegment.direction === "up" ? "\u4E0A" : "\u4E0B"}\u7EBF\u6BB5\u5185\u90E8\u3002\u5F53\u524D\u8FD9\u6BB5\u7EBF\u6BB5\u8FD8\u5728\u5EF6\u4F38\u4E2D\uFF0C\u56E0\u6B64\u8FD9\u6839K\u7EBF\u4E0D\u662F\u5DF2\u786E\u8BA4\u7AEF\u70B9\u3002`
      };
    }
  }
  return {
    type: "none",
    explanation: `\u8BE5K\u7EBF\u4F4D\u4E8E\u7B2C${targetPenIndex + 1}\u7B14\u4E2D\uFF0C\u4F46\u5F53\u524D\u65E2\u4E0D\u662F\u5DF2\u786E\u8BA4\u7EBF\u6BB5\u7AEF\u70B9\uFF0C\u4E5F\u4E0D\u662F\u6B63\u5728\u88AB\u6821\u9A8C\u7684\u5019\u9009\u7AEF\u70B9\u6838\u5FC3K\u7EBF\u3002\u901A\u5E38\u8BF4\u660E\u5B83\u53EA\u662F\u7EBF\u6BB5\u5185\u90E8\u666E\u901AK\u7EBF\u3002`
  };
}
function buildChanAutoDrawResult(data) {
  if (!data || data.length < 7) {
    return { pens: [], segments: [], lines: [] };
  }
  const rawBars = data.map((bar, rawIndex) => ({ ...bar, rawIndex }));
  const standardBars = buildStandardBars(rawBars);
  const fractals = compressFractals(detectFractals(standardBars, rawBars));
  const pens = buildPens(fractals, rawBars);
  const segments = buildSegments(pens);
  const latestBar = rawBars[rawBars.length - 1];
  const lines = [
    ...pens.map((pen) => ({
      id: `pen-${pen.index}`,
      kind: "pen",
      direction: pen.direction,
      startTimestamp: pen.startTimestamp,
      startPrice: pen.startPrice,
      endTimestamp: pen.endTimestamp,
      endPrice: pen.endPrice,
      confirmed: pen.confirmed
    })),
    ...segments.map((segment) => ({
      id: `segment-${segment.index}`,
      kind: "segment",
      direction: segment.direction,
      startTimestamp: segment.startTimestamp,
      startPrice: segment.startPrice,
      endTimestamp: segment.endTimestamp,
      endPrice: segment.endPrice,
      confirmed: segment.confirmed,
      finishMode: segment.finishMode
    }))
  ];
  const lastPen = pens[pens.length - 1];
  if (lastPen && latestBar.timestamp > lastPen.endTimestamp) {
    const direction = lastPen.direction === "up" ? "down" : "up";
    lines.push({
      id: `pen-active-${latestBar.rawIndex}`,
      kind: "pen",
      direction,
      startTimestamp: lastPen.endTimestamp,
      startPrice: lastPen.endPrice,
      endTimestamp: latestBar.timestamp,
      endPrice: direction === "up" ? latestBar.high : latestBar.low,
      confirmed: false
    });
  }
  return { pens, segments, lines };
}
export {
  buildChanAutoDrawResult,
  diagnoseFractal,
  diagnoseSegmentEndpoint
};
