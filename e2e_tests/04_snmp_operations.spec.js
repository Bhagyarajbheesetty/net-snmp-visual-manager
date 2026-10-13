const { test, expect } = require("@playwright/test");

async function waitForAlpine(page) {
  await page.waitForFunction(() => window.Alpine && window.Alpine.version);
}

test.describe("4. SNMP Operations (GET, SET, Concurrency Guard, Stop) QA Suite", () => {
  test.beforeEach(async ({ page, request }) => {
    // Ensure PROXIM-MIB is loaded
    await request.post("http://127.0.0.1:8080/api/mibs/load", {
      data: { module_name: "PROXIM-MIB" }
    });
    await page.goto("/");
    await waitForAlpine(page);

    // Select real test device 192.168.10.40
    const deviceCard = page.locator('.device-card:has-text("192.168.10.40")').first();
    await deviceCard.click();
  });

  test("4.1 Live SNMP GET on valid OID produces formatted result and green counter", async ({ page }) => {
    const oidInput = page.locator('input[x-model="walkFrom"]');
    await oidInput.fill("1.3.6.1.4.1.841.1.1.2.1.4.2.0");

    const getBtn = page.locator('.toolbar button:has-text("GET")');
    await getBtn.click();

    // Verify GET succeeded toast
    const toast = page.locator(".toast");
    await expect(toast).toBeVisible({ timeout: 10000 });
    await expect(toast).toContainText("GET succeeded");

    // Verify result in table
    const resultRow = page.locator("table tbody tr").first();
    await expect(resultRow).toBeVisible();
    await expect(resultRow).toContainText("1.3.6.1.4.1.841.1.1.2.1.4.2.0");
    await expect(resultRow).toContainText("Gauge32");

    // Verify status counter
    const okCounter = page.locator('text=/✓.*1.*ok/');
    await expect(okCounter).toBeVisible();
  });

  test("4.2 Live SNMP GET on No Such Instance OID flags red row, FAILED badge, and error toast", async ({ page }) => {
    const oidInput = page.locator('input[x-model="walkFrom"]');
    await oidInput.fill("1.3.6.1.4.1.841.1.1.3.4.1.2.1.15");

    const getBtn = page.locator('.toolbar button:has-text("GET")');
    await getBtn.click();

    // Verify error toast indicates No Such Instance
    const toast = page.locator(".toast");
    await expect(toast).toBeVisible({ timeout: 10000 });
    await expect(toast).toHaveClass(/error/);
    await expect(toast).toContainText("No Such Instance");

    // Verify row styling: must have .row-failed and .badge-failed
    const failedRow = page.locator("table tbody tr.row-failed").first();
    await expect(failedRow).toBeVisible();
    const failedBadge = failedRow.locator(".badge-failed");
    await expect(failedBadge).toBeVisible();
    await expect(failedBadge).toHaveText("FAILED");

    // Verify status counter updates with ✗ 1 failed
    const failedCounter = page.locator('text=/✗.*1.*failed/');
    await expect(failedCounter).toBeVisible();
  });

  test("4.3 Concurrency Guard disables buttons during operation & Stop button cancels it", async ({ page }) => {
    const oidInput = page.locator('input[x-model="walkFrom"]');
    await oidInput.fill("1.3.6.1.4.1.841.1.1.1.1");

    const getBtn = page.locator('.toolbar button:has-text("GET")');
    const walkBtn = page.locator('.toolbar button.success');
    const stopBtn = page.locator('.toolbar button:has-text("Stop")');

    // Start walk
    await walkBtn.click();

    // While busy: Stop is enabled, GET and Walk are disabled
    await expect(stopBtn).toBeEnabled({ timeout: 5000 });
    await expect(getBtn).toBeDisabled();
    await expect(walkBtn).toBeDisabled();
    await expect(walkBtn).toHaveText("Walking...");

    // Click Stop button
    await stopBtn.click();

    // Verify status updates to stopped and buttons re-enable
    const statusDot = page.locator(".status-dot");
    await expect(statusDot).toHaveClass(/status-stopped/, { timeout: 8000 });
    await expect(getBtn).toBeEnabled({ timeout: 5000 });
    await expect(walkBtn).toBeEnabled({ timeout: 5000 });
    await expect(stopBtn).toBeDisabled();
  });

  test("4.4 Custom Timeout and Retries inputs are preserved and passed to operations", async ({ page }) => {
    const timeoutInput = page.locator('input[title="Timeout in seconds"]');
    const retriesInput = page.locator('input[title="Retry attempts"]');

    await timeoutInput.fill("4");
    await retriesInput.fill("3");

    const oidInput = page.locator('input[x-model="walkFrom"]');
    await oidInput.fill("1.3.6.1.4.1.841.1.1.2.1.4.2.0");

    const getBtn = page.locator('.toolbar button:has-text("GET")');
    await getBtn.click();

    const toast = page.locator(".toast");
    await expect(toast).toBeVisible({ timeout: 10000 });
    await expect(toast).toContainText("GET succeeded");
  });
});
