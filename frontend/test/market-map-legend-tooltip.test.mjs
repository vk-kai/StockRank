import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'

const __dirname = dirname(fileURLToPath(import.meta.url))
const source = readFileSync(resolve(__dirname, '../src/MarketMap.vue'), 'utf8')

assert.match(source, /:data-tooltip="'涨停：'\s*\+\s*legendCounts\.limit_up\s*\+\s*' 只'"/)
assert.match(source, /:data-tooltip="'跌停：'\s*\+\s*legendCounts\.limit_down\s*\+\s*' 只'"/)
assert.match(source, /:data-tooltip="s\.countTitle\s*\+\s*'：'\s*\+\s*legendCounts\[String\(s\.value\)\]\s*\+\s*' 只'"/)
assert.match(source, /class="mm-legend-label">涨停<\/span>/)
assert.match(source, /class="mm-legend-count">\{\{ legendCounts\.limit_up \}\}只<\/span>/)
assert.match(source, /class="mm-legend-label">跌停<\/span>/)
assert.match(source, /class="mm-legend-count">\{\{ legendCounts\.limit_down \}\}只<\/span>/)
assert.match(source, /class="mm-legend-step-label">\{\{ s\.label \}\}<\/span>/)
assert.match(source, /class="mm-legend-step-count">\{\{ legendCounts\[String\(s\.value\)\] \}\}只<\/span>/)
assert.match(source, /class="mm-legend-tooltip"/)
assert.match(source, /legendTooltip:\s*\{\s*visible:\s*false,\s*text:\s*'',\s*x:\s*0,\s*y:\s*0\s*\}/)
assert.match(source, /showLegendTooltip\(e,\s*text\)/)
assert.match(source, /hideLegendTooltip\(\)/)
assert.match(source, /@mouseenter="showLegendTooltip\(\$event,\s*'涨停：'\s*\+\s*legendCounts\.limit_up\s*\+\s*' 只'\)"/)
assert.match(source, /@mouseenter="showLegendTooltip\(\$event,\s*s\.countTitle\s*\+\s*'：'\s*\+\s*legendCounts\[String\(s\.value\)\]\s*\+\s*' 只'\)"/)
assert.match(source, /\.mm-legend-tooltip/)
assert.match(source, /\.mm-legend-count/)
assert.match(source, /\.mm-legend-step-count/)
assert.doesNotMatch(source, /\.mm-legend \[data-tooltip\]::after/)
assert.doesNotMatch(source, /:title=.*legendCounts/)
assert.doesNotMatch(source, />\{\{ s\.label \}\}\s*\{\{ legendCounts/)
