// Apply the shared development key after caller options so it cannot be dropped.
export function withApiKey(options, key) {
  const headers = new Headers(options.headers);
  headers.set('X-API-Key', key);
  return {...options, headers};
}
