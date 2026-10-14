const { test, expect } = require("@playwright/test");

async function waitForAlpine(page) {
  await page.waitForFunction(() => window.Alpine && window.Alpine.version);
}

test.describe("5. Walk, Live Results, Filters, and Export QA Suite", () => {
  let selectedIp = "";

  test.beforeEach(async ({ page, request }) => {
    // Ensure IF-MIB is loaded
    await request.post("http://127.0.0.1:8080/api/mibs/load", {
      data: { module_name: "IF-MIB" }
    });
    await page.goto("/");
    await waitForAlpine(page);

    // Select real test device dynamically
    const deviceCard = page.locator('.device-card').first();
    selectedIp = (await deviceCard.locator('.meta.mono').innerText()).split(':')[0].trim();
    await deviceCard.click();
  });

  test("5.1 Live BulkWalk tracks varbinds, counters, and filters results", async ({ page }) => {
    const oidInput = page.locator('input[x-model="walkFrom"]');
    await oidInput.fill("1.3.6.1.4.1.841.1.1.1.1");

    const walkBtn = page.locator('.toolbar button.success');
    await walkBtn.click();

    // Wait until walk finishes
    const statusDot = page.locator(".content .status-dot");
    await expect(statusDot).toHaveClass(/status-completed/, { timeout: 35000 });

    // Verify counters in status bar
    const okCounter = page.locator('text=/✓.*answered/');
    await expect(okCounter).toBeVisible();

    const allFilter = page.locator('button.filter-pill:has-text("All")');
    const successFilter = page.locator('button.filter-pill:has-text("Success")');
    const failedFilter = page.locator('button.filter-pill:has-text("Failed")');

    await expect(allFilter).toBeVisible();
    await expect(successFilter).toBeVisible();
    await expect(failedFilter).toBeVisible();

    // Verify table has rows
    const rows = page.locator("table tbody tr");
    const totalRows = await rows.count();
    expect(totalRows).toBeGreaterThan(0);

    // Filter by Failed if any failed items exist
    if (await failedFilter.isEnabled()) {
      await failedFilter.click();
      const failedRowCount = await rows.count();
      for (let i = 0; i < Math.min(failedRowCount, 5); i++) {
        await expect(rows.nth(i)).toHaveClass(/row-failed/);
      }

      // Switch back to All
      await allFilter.click();
      expect(await rows.count()).toBe(totalRows);
    }
  });

  test("5.2 Clear Results button resets table and counters", async ({ page }) => {
    // Run GET to have at least one result
    const oidInput = page.locator('input[x-model="walkFrom"]');
    await oidInput.fill("1.3.6.1.4.1.841.1.1.2.1.4.2.0");
    await page.locator('.toolbar button:has-text("GET")').click();

    const rows = page.locator("table tbody tr");
    await expect(rows.first()).toBeVisible({ timeout: 10000 });

    const clearBtn = page.locator('.toolbar button:has-text("Clear")');
    await expect(clearBtn).toBeEnabled();
    await clearBtn.click();

    // Results table should hide and empty state appear
    await expect(rows).toHaveCount(0);
    const emptyState = page.locator(".results-area .empty-state");
    await expect(emptyState).toBeVisible();
  });

  test("5.3 Export modal previews formatted text with SNMP Agent & Query Results", async ({ page }) => {
    const oidInput = page.locator('input[x-model="walkFrom"]');
    await oidInput.fill("1.3.6.1.4.1.841.1.1.1.1");
    await page.locator('.toolbar button.success').click();
    
    // Wait for walk completion
    const statusDot = page.locator(".content .status-dot");
    await expect(statusDot).toHaveClass(/status-completed/, { timeout: 35000 });
    await expect(page.locator("table tbody tr").first()).toBeVisible();

    const exportBtn = page.locator('.toolbar button:has-text("Export")');
    await expect(exportBtn).toBeEnabled();
    await exportBtn.click();

    const exportModal = page.locator('.modal:has(h2:has-text("Export Walk Results"))');
    await expect(exportModal).toBeVisible();

    const preview = exportModal.locator(".export-preview");
    await expect(preview).toBeVisible();
    await expect(preview).toContainText("[SNMP Agent]");
    await expect(preview).toContainText("[Query Results]");
    await expect(preview).toContainText(selectedIp);

    // Close export modal
    const closeBtn = exportModal.locator('button:has-text("Close")');
    await closeBtn.click();
    await expect(exportModal).not.toBeVisible();
  });
});
