from __future__ import annotations

import os

import pytest
from playwright.sync_api import sync_playwright

WEB_RECIPE_LAYOUT_URL_ENV = "DEVRADAR_WEB_RECIPE_LAYOUT_URL"


@pytest.mark.skipif(
    not os.getenv(WEB_RECIPE_LAYOUT_URL_ENV),
    reason=f"set {WEB_RECIPE_LAYOUT_URL_ENV} to test the live dashboard layout",
)
def test_recipe_identity_never_collapses_or_overlaps_metadata() -> None:
    base_url = os.environ[WEB_RECIPE_LAYOUT_URL_ENV].rstrip("/")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 1000})
        try:
            page.goto(f"{base_url}/sources?view=collector", wait_until="domcontentloaded")
            page.locator(".recipe-list-item").first.wait_for(state="visible")

            for width in (1280, 1917):
                page.set_viewport_size({"width": width, "height": 1000})
                page.wait_for_timeout(100)
                rows = page.locator(".recipe-list-item").evaluate_all(
                    """
                    (items) => items.map((row) => {
                      const identity = row.querySelector('.recipe-identity');
                      const identityLeaves = Array.from(
                        identity.querySelectorAll('strong,.badge,small'),
                      ).filter((node) => node.getClientRects().length > 0);
                      const metadataLeaves = Array.from(row.querySelectorAll(
                        '.recipe-scope strong,.recipe-scope small,' +
                        '.recipe-last-used strong,.recipe-last-used small,' +
                        ':scope > .badge',
                      )).filter((node) => node.getClientRects().length > 0);
                      const intersects = (left, right) => {
                        const a = left.getBoundingClientRect();
                        const b = right.getBoundingClientRect();
                        return Math.min(a.right, b.right) > Math.max(a.left, b.left) &&
                          Math.min(a.bottom, b.bottom) > Math.max(a.top, b.top);
                      };
                      return {
                        identityWidth: identity.getBoundingClientRect().width,
                        collapsedIdentityLeaves: identityLeaves
                          .filter((node) => node.getBoundingClientRect().width < 1)
                          .map((node) => node.textContent.trim()),
                        overlaps: identityLeaves.flatMap((identityNode) =>
                          metadataLeaves
                            .filter((metadataNode) => intersects(identityNode, metadataNode))
                            .map((metadataNode) => [
                              identityNode.textContent.trim(),
                              metadataNode.textContent.trim(),
                            ]),
                        ),
                      };
                    })
                    """
                )

                assert rows
                assert all(row["identityWidth"] >= 96 for row in rows), rows
                assert all(not row["collapsedIdentityLeaves"] for row in rows), rows
                assert all(not row["overlaps"] for row in rows), rows
                assert page.evaluate(
                    "document.documentElement.scrollWidth <= "
                    "document.documentElement.clientWidth + 1"
                )
        finally:
            browser.close()
