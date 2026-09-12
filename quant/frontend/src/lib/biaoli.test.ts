import { classifyBiaoliLevels, type LevelBiaoliState } from "./biaoli";

function state(period: string, X: 1 | -1, Y: 0 | 1): LevelBiaoliState {
  return {
    period,
    level: period,
    X,
    Y,
    code: `(${X},${Y})`,
    penLabel: "",
    hint: "",
    klineCount: 300,
  };
}

function assertEqual(actual: string, expected: string, message: string) {
  if (actual !== expected) {
    throw new Error(`${message}: expected "${expected}", got "${actual}"`);
  }
}

const topObservation = classifyBiaoliLevels(
  [state("5", -1, 1), state("30", 1, 1), state("daily", 1, 0)],
  "短线"
);
assertEqual(topObservation.stage, "见顶观察", "large (1,0) with small-level pullback is observation, not reversal");

const bottomObservation = classifyBiaoliLevels(
  [state("5", 1, 1), state("30", -1, 1), state("daily", -1, 0)],
  "短线"
);
assertEqual(bottomObservation.stage, "见底观察", "large (-1,0) with small-level rebound is observation, not reversal");

const strongUp = classifyBiaoliLevels(
  [state("5", 1, 1), state("30", 1, 1), state("daily", 1, 1)],
  "短线"
);
assertEqual(strongUp.stage, "强势上涨", "aligned upward extensions remain strong-up state");
