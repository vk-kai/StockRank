import { PERIODS } from "../types";

interface Props {
  selectedPeriod: string;
  onSelect: (period: string) => void;
  showDrawPanel?: boolean;
  onToggleDrawPanel?: () => void;
}

export default function PeriodSelector({
  selectedPeriod,
  onSelect,
  showDrawPanel = false,
  onToggleDrawPanel,
}: Props) {
  return (
    <div className="period-selector">
      {PERIODS.map((p) => {
        const isLastPeriodButton = p.value === "120";
        return (
          <div key={p.value} className="period-selector-item">
            <button
              className={`period-btn ${selectedPeriod === p.value ? "active" : ""}`}
              onClick={() => onSelect(p.value)}
            >
              {p.label}
            </button>
            {isLastPeriodButton && (
              <div className="draw-toolbar-wrap">
                <button
                  type="button"
                  className={`period-btn auto-draw-btn ${showDrawPanel ? "active" : ""}`}
                  onClick={onToggleDrawPanel}
                  title="打开主图右侧画线侧边栏"
                >
                  画线
                </button>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
