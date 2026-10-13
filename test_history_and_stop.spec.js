const { test, expect } = require("@playwright/test");

async function waitForAlpine(page) {
  await page.waitForFunction(() => window.Alpine && window.Alpine.version);
}

test.describe("History Management & Operation Concurrency / Stop Verification", () => {
  test.beforeEach(async ({ page, request }) => {
    // Ensure IF-MIB is loaded
    await request.post("http://127.0.0.1:8080/api/mibs/load", {
      data: { module_name: "IF-MIB" }
    });
    await page.goto("http://127.0.0.1:8080/");
    await waitForAlpine(page);
  });

  test("1. Clear History button clears all records", async ({ page, request }) => {
    // Switch to History tab
    const historyTab = page.locator('.tab:has-text("History")');
    await historyTab.click();

    // Dialog handler to auto-accept confirmation
    page.on("dialog", dialog => dialog.accept());

    const clearHistoryBtn = page.locator('button:has-text("Clear History")');
    await expect(clearHistoryBtn).toBeVisible();

    // If there are records or if disabled when empty
    if (await clearHistoryBtn.isEnabled()) {
      await clearHistoryBtn.click();
      await expect(page.locator('text=No query history')).toBeVisible({ timeout: 5000 });
    } else {
      await expect(page.locator('text=No query history')).toBeVisible();
    }
  });

  test("2. Stop button terminates active operation and isBusy guards against duplicate clicks", async ({ page }) => {
    // Select first device
    const deviceCard = page.locator('.device-card').first();
    await deviceCard.click();

    // Verify GET button is enabled initially
    const getBtn = page.locator('.toolbar button:has-text("GET")');
    const walkBtn = page.locator('.toolbar button.success');
    const stopBtn = page.locator('.toolbar button:has-text("Stop")');

    await expect(getBtn).toBeEnabled();
    await expect(walkBtn).toBeEnabled();
    await expect(stopBtn).toBeDisabled();

    // Start a walk
    await walkBtn.click();

    // Now walk is running: Stop button must be enabled, GET and Walk button disabled
    await expect(stopBtn).toBeEnabled({ timeout: 5000 });
    await expect(getBtn).toBeDisabled();
    await expect(walkBtn).toBeDisabled();
    await expect(walkBtn).toHaveText("Walking...");

    // Click Stop button
    await stopBtn.click();

    // After stop, walkStatus must be stopped and buttons re-enabled
    const statusDot = page.locator(".status-dot");
    await expect(statusDot).toHaveClass(/status-stopped/, { timeout: 8000 });
    await expect(getBtn).toBeEnabled({ timeout: 5000 });
    await expect(walkBtn).toBeEnabled({ timeout: 5000 });
    await expect(stopBtn).toBeDisabled();
  });
});


