const { test, expect } = require("@playwright/test");

async function waitForAlpine(page) {
  await page.waitForFunction(() => window.Alpine && window.Alpine.version);
}

test("page loads with all UI sections", async ({ page }) => {
  await page.goto("http://127.0.0.1:8080/");
  await waitForAlpine(page);
  await expect(page.locator("h1")).toContainText("SNMP Visual Manager");
  await expect(page.locator('.tab:has-text("Devices")')).toBeVisible();
  await expect(page.locator('.tab:has-text("MIB Modules")')).toBeVisible();
  await expect(page.locator('.tab:has-text("History")')).toBeVisible();
});


