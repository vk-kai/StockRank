# 大盘云图 · 图例点击筛选功能 设计

- 日期：2026-07-01
- 范围：`StockRank/frontend/src/MarketMap.vue`（纯前端，单文件，约 90 行改动）
- 不改后端、不改数据结构。

## 目标

让右下角图例 `mm-legend-bar`（9 个涨跌幅色块）可点击，按涨跌幅区间筛选高亮个股；并新增「涨停」「跌停」两个按钮。命中股保持原色，未命中股灰显；再次点击复原。

## 行为

- **就地灰显（不重排）**：命中股保持原色与位置；未命中股填充暗灰 `#1b2330`、不画文字标签。
- **互斥单选**：同一时刻只有一个筛选生效。再次点击当前触发器 → 复原（`activeLegend = null`）；点击另一个 → 切换。
- **整板块变暗**：当某一级行业（L1 sector）一只都没命中时，在该板块绘制完内容后叠加一层暗色面纱 `rgba(8,14,24,0.78)`，使其标题条 / 二级标题 / 边框 / 个股统一变暗。
- 与搜索高亮互不干扰、可并用；刷新行情后筛选状态保持；悬停灰显股时 tooltip 仍显示真实涨跌幅。

## 筛选触发器取值（`activeLegend`）

`null`（无筛选）｜ 数值 `-4..4`（色块）｜ `'limit_up'`（涨停）｜ `'limit_down'`（跌停）。

### ① 9 色块涨跌幅区间（半开区间，左开右闭，两极延伸至 ±∞）

| 色块 | 命中区间 |
|---|---|
| -4 | `change ≤ -4` |
| -3 | `-4 < change ≤ -3` |
| -2 | `-3 < change ≤ -2` |
| -1 | `-2 < change ≤ -1` |
| 0 | `-1 < change ≤ 0` |
| +1 | `0 < change ≤ 1` |
| +2 | `1 < change ≤ 2` |
| +3 | `2 < change ≤ 3` |
| +4 | `change > 3` |

（与用户示例一致：点 -4 → 跌幅 ≥4%；点 -3 → -3 到 -4 之间。）

### ② 涨停 / 跌停（板块感知）

按代码前缀（取 6 位数字）识别限幅：

- 主板 `60/00` → ±10%
- 创业板 `300/301`、科创板 `688` → ±20%
- 北交所 `8/4` 开头 → ±30%

判定：涨停 `change ≥ 限幅 - 0.1`；跌停 `change ≤ -(限幅 - 0.1)`。

局限：ST/*ST（±5%）数据无标记，会漏判，可接受。

## 实现

1. 模块级常量：`DIM_COLOR = '#1b2330'`、`VEIL_COLOR = 'rgba(8,14,24,0.78)'`。
2. 模块级纯函数：
   - `limitThreshold(code)`：按前缀返回 10/20/30。
   - `inFilter(change, code, active)`：实现上表与涨跌停判定；`active==null` 恒真；`change` 为空值时非涨跌停/非区间命中 → 返回 false（被灰显）。
3. `data` 增加 `activeLegend: null`。
4. `computed.legendSteps`：每项增加 `value`（=COLOR_STOPS 阈值）与 `title`（区间说明，供 hover）。
5. `computed.filterBadge`：`activeLegend` 非空时返回 `{ desc, count }`；遍历 `this.tree` 统计命中个股数；desc 按区间/涨跌停生成文案。
6. 方法：`toggleFilter(v)`（相同置 null 否则置 v，再 `render()`）、`clearFilter()`（置 null 再 `render()`）。
7. `render()` 个股循环：`matched = active==null || inFilter(st.change, st.code, active)`；`fillStyle = matched ? st.color : DIM_COLOR`；仅 `matched` 时画 `drawStockLabel`；维护 `sectorHasMatch` 标志，L1 标题/边框画完后若 `active!=null && !sectorHasMatch` 叠加 `VEIL_COLOR` 面纱。
8. 模板：
   - 色块加 `@click="toggleFilter(s.value)"`、`:class="{active: activeLegend===s.value}"`、`:title="s.title"`。
   - 图例容器内新增 `[涨停]`（红）/`[跌停]`（绿）按钮，`@click` 绑 `toggleFilter('limit_up'/'limit_down')`，`:class="{active:...}"`。
   - 画布容器内新增筛选状态条 `mm-filter-badge`（`v-if="filterBadge"`）：「已筛选：desc（N 只）✕」，点击调 `clearFilter`。
9. 样式：
   - 移除 `.mm-legend { pointer-events:none }`，改为 `display:flex; align-items:center; gap:6px`。
   - `.mm-legend-step` 加 `cursor:pointer; transition`；`:hover` 上抬放大；`.active` 白色外发光描边 + 上抬。
   - `.mm-limit-btn`（涨红/跌绿配色，与「红涨绿跌」一致），`.active` 高亮。
   - `.mm-filter-badge` 绝对定位置于画布顶部居中，可点击清除。

## 验证

无测试框架，改用 `npm run build`（vite build）确保模板/语法无误；逻辑通过纯函数 `inFilter` / `limitThreshold` 在 spec 内的自检样例覆盖（见下）。

### 自检样例

- `inFilter(-4.5, _, -4)` → true；`inFilter(-3.5, _, -4)` → false。
- `inFilter(-3.5, _, -3)` → true；`inFilter(-3.0, _, -3)` → true（右闭）；`inFilter(-4.0, _, -3)` → false。
- `inFilter(3.5, _, 4)` → true；`inFilter(3.0, _, 4)` → false。
- 涨停：`limitThreshold('sh688981')===20`、`'300750'===20`、`'600519'===10`、`'830xxx'===30`；`inFilter(10.0,'600519','limit_up')`→true；`inFilter(9.8,'600519','limit_up')`→false；`inFilter(15.0,'688981','limit_up')`→false（未达 20%）。
