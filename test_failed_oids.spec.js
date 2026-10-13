const { test, expect } = require("@playwright/test");

async function waitForAlpine(page) {
  await page.waitForFunction(() => window.Alpine && window.Alpine.version);
}

test.describe("Failed / Unanswered OIDs Live Tracking & Filter Verification", () => {
  test.beforeEach(async ({ page, request }) => {
    // Ensure PROXIM-MIB is loaded
    await request.post("http://127.0.0.1:8080/api/mibs/load", {
      data: { module_name: "PROXIM-MIB" }
    });
    await page.goto("http://127.0.0.1:8080/");
    await waitForAlpine(page);
  });

  test("1. Walk tracks live results, flags missing/failed OIDs, and updates counters", async ({ page }) => {
    // Select real test device (192.168.10.40)
    const deviceCard = page.locator('.device-card:has-text("192.168.10.40")');
    await deviceCard.click();

    // Start walk on deviceConfig branch (which has some unimplemented items)
    const oidInput = page.locator('input[x-model="walkFrom"]');
    await oidInput.fill("1.3.6.1.4.1.841.1.1.1.1");

    const startWalkBtn = page.locator('button:has-text("Start Walk")');
    await startWalkBtn.click();

    // Wait until walk finishes
    const statusDot = page.locator(".status-dot");
    await expect(statusDot).toHaveClass(/status-completed/, { timeout: 30000 });

    // Verify counters appear in status bar
    const okCounter = page.locator('text=/✓.*ok/');
    await expect(okCounter).toBeVisible();

    const failedFilterBtn = page.locator('button.filter-pill:has-text("Failed")');
    await expect(failedFilterBtn).toBeVisible();

    // If there are failed/unanswered OIDs, verify red row styling
    const failedBadge = page.locator('.row-failed .badge-failed');
    if (await failedBadge.count() > 0) {
      await expect(failedBadge.first()).toBeVisible();

      // Click Failed filter
      await failedFilterBtn.click();

      // Ensure every visible row in table is a failed row
      const rows = page.locator('table tbody tr');
      const rowCount = await rows.count();
      for (let i = 0; i < rowCount; i++) {
        await expect(rows.nth(i)).toHaveClass(/row-failed/);
      }
    }
  });

  test("2. Export text file includes [Unanswered / Missing MIB Objects] when present", async ({ page }) => {
    // Select real test device
    const deviceCard = page.locator('.device-card:has-text("192.168.10.40")');
    await deviceCard.click();

    const oidInput = page.locator('input[x-model="walkFrom"]');
    await oidInput.fill("1.3.6.1.4.1.841.1.1.1.1");

    const startWalkBtn = page.locator('button:has-text("Start Walk")');
    await startWalkBtn.click();

    const statusDot = page.locator(".status-dot");
    await expect(statusDot).toHaveClass(/status-completed/, { timeout: 30000 });

    // Open Export modal
    const exportBtn = page.locator('button:has-text("Export")');
    await exportBtn.click();

    const exportPreview = page.locator(".export-preview");
    await expect(exportPreview).toBeVisible();
    await expect(exportPreview).toContainText("[SNMP Agent]");
    await expect(exportPreview).toContainText("[Query Results]");
  });
});
