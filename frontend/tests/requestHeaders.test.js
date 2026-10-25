import test from 'node:test';
import assert from 'node:assert/strict';
import {withApiKey} from '../src/requestHeaders.js';

test('current-course JSON request keeps authentication and content type', () => {
  const original = {method:'POST', headers:{'Content-Type':'application/json'}, body:'[]'};
  const result = withApiKey(original, 'test-key');
  assert.equal(result.headers.get('X-API-Key'), 'test-key');
  assert.equal(result.headers.get('Content-Type'), 'application/json');
  assert.equal(result.body, '[]');
  assert.deepEqual(original.headers, {'Content-Type':'application/json'});
});
test('uploads leave multipart boundary to the browser', () => {
  const result = withApiKey({method:'POST'}, 'test-key');
  assert.equal(result.headers.get('X-API-Key'), 'test-key');
  assert.equal(result.headers.has('Content-Type'), false);
});
