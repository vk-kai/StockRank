import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'

const __dirname = dirname(fileURLToPath(import.meta.url))
const script = readFileSync(resolve(__dirname, '../src/components/NewsPage/NewsPage.script.js'), 'utf8')

assert.match(script, /getScoreLabel\(score\)/)
assert.match(script, /if \(score >= 55\) return ['"`][^'"`]*['"`]/)
assert.match(script, /if \(score <= 45\) return ['"`][^'"`]*['"`]/)
assert.match(script, /newsItem\.ai_label = this\.getScoreLabel\(newsItem\.ai_score\)/)

assert.match(script, /overallScore >= 55 \? '#ef4444'/)
assert.match(script, /overallScore <= 45 \? '#22c55e'/)
assert.match(script, /overallScore >= 55 \? ['"`][^'"`]*['"`]/)
assert.match(script, /overallScore <= 45 \? ['"`][^'"`]*['"`]/)

assert.match(script, /if \(score >= 55\) return 'score-positive'/)
assert.match(script, /if \(score <= 45\) return 'score-negative'/)
assert.doesNotMatch(script, /score > 50/)
assert.doesNotMatch(script, /score < 50/)
assert.doesNotMatch(script, /overallScore > 50/)
assert.doesNotMatch(script, /overallScore < 50/)
