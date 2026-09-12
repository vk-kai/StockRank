const SH_INDEX_CODES = new Set([
  "000001",
  "000300",
  "000905",
  "000852",
  "000016",
  "000903",
  "000819",
  "000849",
  "000922",
  "000932",
  "000991",
  "000993",
]);

export function isIndexCode(code: string, name: string): boolean {
  if (SH_INDEX_CODES.has(code)) return true;
  if (code.startsWith("399")) return true;
  if (name.includes("指数") || name.includes("成指") || name.includes("板指")) return true;
  return false;
}
