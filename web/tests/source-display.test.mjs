import assert from "node:assert/strict";
import test from "node:test";

test("collector source names become bounded presentation labels", async () => {
  const display = await import("../src/lib/source-display.ts");
  assert.equal(
    display.sourceDisplayName({
      name: "Collector · www.topcv.vn [f1fe63e0]",
      url: "https://www.topcv.vn",
    }),
    "topcv.vn",
  );
  assert.equal(
    display.sourceDisplayName({ name: "NAVER Vietnam", url: "https://example.com" }),
    "NAVER Vietnam",
  );
});
