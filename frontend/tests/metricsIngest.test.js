import test from 'node:test';
import assert from 'node:assert/strict';
import { makeTemporaryStudentId, requireCompleteIngest } from '../src/metricsIngest.js';

test('temporary IDs stay within the backend schema [1,1000000]', () => {
  assert.equal(makeTemporaryStudentId(0), 1);
  assert.equal(makeTemporaryStudentId(0.5), 500001);
  assert.equal(makeTemporaryStudentId(0.9999999999999999), 1000000);
});

test('reject invalid random values rather than producing malformed IDs', () => {
  for (const value of [-1, 1, Number.NaN, Number.POSITIVE_INFINITY]) {
    assert.throws(() => makeTemporaryStudentId(value), RangeError);
  }
});

test('only complete, zero-error ingestion can show success', () => {
  const response = { rows_ok: 2, rows_skipped: 0, errors: [] };
  assert.equal(requireCompleteIngest(response, 2), response);
  assert.throws(() => requireCompleteIngest(response, 0), /empty/);
});

test('detect a partial ingest even on HTTP 200', () => {
  const cases = [
    { rows_ok: 1, rows_skipped: 1, errors: ['row 2: failed'] },
    { rows_ok: 1, rows_skipped: 0, errors: [] },
    { rows_ok: 2, rows_skipped: 1, errors: [] },
    { rows_ok: 2, rows_skipped: 0, errors: ['validation error'] },
    { rows_ok: '2', rows_skipped: 0, errors: [] },
    null,
    {},
  ];
  for (const response of cases) {
    assert.throws(() => requireCompleteIngest(response, 2), /did not confirm/);
  }
});
