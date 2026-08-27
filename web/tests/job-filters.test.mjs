import assert from "node:assert/strict";
import test from "node:test";

test("job source filter accepts one UUID and rejects ambiguous or malformed input", async () => {
  const { parseJobSourceId } = await import("../src/lib/job-filters.ts");
  const sourceId = "11ee2f80-2d9b-46a3-ba4f-42c79b0a7082";

  assert.equal(parseJobSourceId(sourceId), sourceId);
  assert.equal(parseJobSourceId(sourceId.toUpperCase()), sourceId.toUpperCase());
  assert.equal(parseJobSourceId("not-a-uuid"), undefined);
  assert.equal(parseJobSourceId([sourceId]), undefined);
  assert.equal(parseJobSourceId([sourceId, "00000000-0000-4000-8000-000000000000"]), undefined);
  assert.equal(parseJobSourceId(undefined), undefined);
});
