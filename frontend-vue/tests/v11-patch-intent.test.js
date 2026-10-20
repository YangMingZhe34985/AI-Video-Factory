import test from 'node:test'
import assert from 'node:assert/strict'
import { patchIntent } from '../src/components/agent/v3-patch.js'
const changed = { element: '猫跳舞', change: 'changed', before: '跳舞', after: '摆动', reason: '动作弱化' }
test('only explicit true and empty changes indicate preserved intent', () => {
  assert.equal(patchIntent({ intent_preserved: true, changed_elements: [] }).status, 'preserved')
  for (const value of [null, {}, { intent_preserved: true }, { intent_preserved: 'true', changed_elements: [] }, { intent_preserved: false, changed_elements: [] }]) assert.equal(patchIntent(value).status, 'unknown')
})
test('changes require human review even if the model claims true', () => {
  for (const preserved of [true, false]) {
    const value = patchIntent({ intent_preserved: preserved, changed_elements: [changed] })
    assert.equal(value.status, 'changed'); assert.deepEqual(value.changes, [changed])
  }
})
test('malformed changes cannot turn a nonempty list into assurance', () => {
  assert.equal(patchIntent({ intent_preserved: true, changed_elements: [null, {}] }).status, 'unknown')
})
