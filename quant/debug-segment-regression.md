# Debug Session: segment-regression
- **Status**: [OPEN]
- **Issue**: 自动补历史报错，且自动线段退化为几乎只剩一个向上线段；同时需要按“先满足线段结束基本条件，假定位端点，再校验深入条件”的口径重做端点确认。
- **Debug Server**: http://127.0.0.1:7777/event
- **Log File**: .dbg/trae-debug-log-segment-regression.ndjson

## Reproduction Steps
1. 打开自动划线，仅在 5 分钟周期使用。
2. 清空起始日期或重新选择起始日期，观察是否出现“自动补历史未能完成，请稍后重试”。
3. 查看自动线段是否退化成几乎只有一个向上线段，向下线段消失。
4. 双击线段拐点附近 K 线，观察特征序列诊断是否符合“先假定位端点，再深入校验”的口径。

## Hypotheses & Verification
| ID | Hypothesis | Likelihood | Effort | Evidence |
|----|------------|------------|--------|----------|
| A | 起始日期切换后的自动补历史流程在某个前端分支提前报错或状态没有复位，导致自动补历史提示异常 | High | Med | Pending |
| B | 最近对 `analyzeSegmentFinish()` 的改动把“假设端点”直接当成“最终端点”，导致大部分向下线段被过滤掉 | High | Med | Rejected by pre-fix logs: 不是提前确认，而是大量扫描根本没有进入有效端点确认 |
| C | 线段拐点扫描现在要求过严，导致只有极少数拐点能通过，最终几乎只剩单方向线段 | High | Med | Confirmed by pre-fix logs: 大量 `pivotCount=0` / `resolvedFinishMode=null`，最终落到 `segment remained active` |
| D | 第一/第二特征序列的左右边界取错，或包含处理跨序列执行，导致特征分型识别失真 | Med | Med | Confirmed by code+logs: 把端点强绑到局部左右拐点，和“前三个特征序列成分型后再取极值端点”的口径不一致 |
| E | 自动补历史失败与线段异常其实共享同一个触发条件：起始日期过滤后的数据范围和线段计算输入不一致 | Med | High | Pending |

## Log Evidence
- Pre-fix log showed repeated `analyze segment finish` entries with `pivotCount=0` and `resolvedFinishMode=null`.
- Pre-fix log also showed repeated `segment remained active`, explaining why chart degenerated into a long single-direction segment.
- User clarification confirmed the intended rule: endpoint should be confirmed from the first/second/third feature sequences as a whole, then take the highest/lowest K line in that fractal region, with inclusion handling applied first.

## Verification Conclusion
- Waiting for post-fix reproduction and log comparison.
