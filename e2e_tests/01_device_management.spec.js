const { test, expect } = require("@playwright/test");

async function waitForAlpine(page) {
  await page.waitForFunction(() => window.Alpine && window.Alpine.version);
}

test.describe("1. Device Management QA Suite", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/");
    await waitForAlpine(page);
  });

  test("1.1 Select Device 192.168.10.40 updates Target Badges and Controls", async ({ page }) => {
    const deviceCard = page.locator('.device-card:has-text("192.168.10.40")').first();
    await expect(deviceCard).toBeVisible();
    await deviceCard.click();

    // Verify prominent Target Pill in Header
    const headerTarget = page.locator('.header .target-badge');
    await expect(headerTarget).toBeVisible();
    await expect(headerTarget).toContainText("192.168.10.40");

    // Verify Target Badge in Status Bar
    const statusBarTarget = page.locator('.toolbar .target-badge');
    await expect(statusBarTarget).toBeVisible();
    await expect(statusBarTarget).toContainText("192.168.10.40");

    // Verify opTimeout and opRetries inputs are loaded
    const timeoutInput = page.locator('input[title="Timeout in seconds"]');
    const retriesInput = page.locator('input[title="Retry attempts"]');
    await expect(timeoutInput).toBeVisible();
    await expect(retriesInput).toBeVisible();
  });

  test("1.2 Test Connection on 192.168.10.40 validates live SNMP connectivity", async ({ page }) => {
    const deviceCard = page.locator('.device-card:has-text("192.168.10.40")').first();
    await expect(deviceCard).toBeVisible();

    const testBtn = deviceCard.locator('button:has-text("Test")');
    await expect(testBtn).toBeVisible();
    await testBtn.click();

    // Live SNMP check must return Connection OK toast
    const toast = page.locator('.toast');
    await expect(toast).toBeVisible({ timeout: 10000 });
    await expect(toast).toContainText("Connection OK");
  });

  test("1.3 Add Device, Edit Device, Cancel Form, and Delete Device Lifecycle", async ({ page }) => {
    const addBtn = page.locator('button:has-text("+ Add Device")');
    await expect(addBtn).toBeVisible();
    await addBtn.click();

    const modal = page.locator('.modal:has(h2:has-text("Add Device"))');
    await expect(modal).toBeVisible();

    // Fill form
    const timestamp = Date.now();
    const tempName = `QA-Temp-${timestamp}`;
    await modal.locator('input[placeholder="My Router"]').fill(tempName);
    await modal.locator('input[placeholder="169.254.128.1"]').fill("127.0.0.1");

    // Cancel test
    const cancelBtn = modal.locator('button:has-text("Cancel")');
    await cancelBtn.click();
    await expect(modal).not.toBeVisible();

    // Reopen and save
    await addBtn.click();
    await modal.locator('input[placeholder="My Router"]').fill(tempName);
    await modal.locator('input[placeholder="169.254.128.1"]').fill("127.0.0.1");
    await modal.locator('button:has-text("Save")').click();
    await expect(modal).not.toBeVisible();

    // Verify created card
    const createdCard = page.locator(`.device-card:has-text("${tempName}")`);
    await expect(createdCard).toBeVisible();

    // Edit device
    const editBtn = createdCard.locator('button:has-text("Edit")');
    await editBtn.click();

    const editModal = page.locator('.modal:has(h2:has-text("Edit Device"))');
    await expect(editModal).toBeVisible();
    const updatedName = `${tempName}-Renamed`;
    await editModal.locator('input[placeholder="My Router"]').fill(updatedName);
    await editModal.locator('button:has-text("Save")').click();
    await expect(editModal).not.toBeVisible();

    const updatedCard = page.locator(`.device-card:has-text("${updatedName}")`);
    await expect(updatedCard).toBeVisible();

    // Delete device with dialog confirmation
    page.on("dialog", dialog => dialog.accept());
    const deleteBtn = updatedCard.locator('button:has-text("Del")');
    await deleteBtn.click();
    await expect(updatedCard).not.toBeVisible({ timeout: 5000 });
  });
});
