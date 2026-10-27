// Small, dependency-free contract checks for classroom feedback.
// IDs are temporary per submission and are not authenticated or stable identities.
export function makeTemporaryStudentId(randomValue = Math.random()) {
  if (!Number.isFinite(randomValue) || randomValue < 0 || randomValue >= 1) {
    throw new RangeError('Random source must return a finite value in [0, 1)');
  }
  return Math.floor(randomValue * 1_000_000) + 1;
}

// A successful HTTP response is not proof that every record was inserted.
export function requireCompleteIngest(report, expectedRows) {
  if (!Number.isSafeInteger(expectedRows) || expectedRows < 1) {
    throw new Error('Cannot submit an empty or invalid metrics batch');
  }
  if (
    !report ||
    typeof report !== 'object' ||
    Array.isArray(report) ||
    !Number.isSafeInteger(report.rows_ok) ||
    !Number.isSafeInteger(report.rows_skipped) ||
    report.rows_ok !== expectedRows ||
    report.rows_skipped !== 0 ||
    !Array.isArray(report.errors) ||
    report.errors.length !== 0
  ) {
    throw new Error('The server did not confirm all feedback records were stored');
  }
  return report;
}
