export interface PeriodOption {
  value: string;
  label: string;
}

export const PERIODS: PeriodOption[] = [
  { value: "intraday", label: "分时" },
  { value: "daily", label: "日K" },
  { value: "weekly", label: "周" },
  { value: "monthly", label: "月" },
  { value: "quarter", label: "季" },
  { value: "year", label: "年" },
  { value: "1", label: "1分" },
  { value: "5", label: "5分" },
  { value: "15", label: "15分" },
  { value: "30", label: "30分" },
  { value: "60", label: "60分" },
  { value: "120", label: "120分" },
];
