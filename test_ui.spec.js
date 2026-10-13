const { test, expect } = require("@playwright/test");

async function waitForAlpine(page) {
  await page.waitForFunction(() => window.Alpine && window.Alpine.version);
}

test("add and cancel device form", async ({ page }) => {
  await page.goto("http://127.0.0.1:8080/");
  await waitForAlpine(page);
  const form = page.locator('div[x-show="showDeviceForm"]');
  await expect(form).not.toBeVisible();
  await page.click('button:has-text("Add Device")');
  await expect(form).toBeVisible();
  await page.click('button:has-text("Cancel")');
  await expect(form).not.toBeVisible();
});


