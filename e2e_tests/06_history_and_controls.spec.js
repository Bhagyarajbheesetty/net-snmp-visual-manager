const { test, expect } = require("@playwright/test");

async function waitForAlpine(page) {
  await page.waitForFunction(() => window.Alpine && window.Alpine.version);
}

test.describe("6. History, Theme, and Keyboard QA Suite", () => {
  test.beforeEach(async ({ page, request }) => {
    // Ensure IF-MIB is loaded
    await request.post("http://127.0.0.1:8080/api/mibs/load", {
      data: { module_name: "IF-MIB" }
    });
    await page.goto("/");
    await waitForAlpine(page);
  });

  test("6.1 History tab records operations and Clear History empties table", async ({ page }) => {
    // First execute a GET operation to ensure at least one history item is logged
    const deviceCard = page.locator('.device-card:has-text("127.0.0.1")').first();
    await deviceCard.click();

    const oidInput = page.locator('input[x-model="walkFrom"]');
    await oidInput.fill("1.3.6.1.4.1.841.1.1.2.1.4.2.0");
    await page.locator('.toolbar button:has-text("GET")').click();
    await page.waitForTimeout(1000);

    // Switch to History tab
    const historyTab = page.locator('.tab:has-text("History")');
    await historyTab.click();

    // Verify history cards appear
    const historyCards = page.locator('div[x-show="sideTab===\'history\'"] .device-card');
    await expect(historyCards.first()).toBeVisible({ timeout: 5000 });

    // Click Clear History button with dialog confirmation
    page.on("dialog", dialog => dialog.accept());
    const clearHistoryBtn = page.locator('button:has-text("Clear History")');
    await expect(clearHistoryBtn).toBeEnabled();
    await clearHistoryBtn.click();

    // Verify empty state appears
    await expect(page.locator('text=No query history')).toBeVisible({ timeout: 5000 });
  });

  test("6.2 Theme toggle button switches between Light and Dark mode", async ({ page }) => {
    const themeBtn = page.locator('button:has-text("Theme")');
    await expect(themeBtn).toBeVisible();

    const htmlEl = page.locator("html");

    // Initially light theme (no .dark class)
    await expect(htmlEl).not.toHaveClass(/dark/);

    // Click Theme -> Dark
    await themeBtn.click();
    await expect(htmlEl).toHaveClass(/dark/);

    // Click Theme -> Light
    await themeBtn.click();
    await expect(htmlEl).not.toHaveClass(/dark/);
  });

  test("6.3 Keyboard Escape shortcut dismisses active modals", async ({ page }) => {
    // Open Add Device modal
    const addBtn = page.locator('button:has-text("+ Add Device")');
    await addBtn.click();

    const modal = page.locator('.modal:has(h2:has-text("Add Device"))');
    await expect(modal).toBeVisible();

    // Press Escape
    await page.keyboard.press("Escape");
    await expect(modal).not.toBeVisible();
  });
});


