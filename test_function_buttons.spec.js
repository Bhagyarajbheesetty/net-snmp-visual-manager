const { test, expect } = require("@playwright/test");

async function waitForAlpine(page) {
  await page.waitForFunction(() => window.Alpine && window.Alpine.version);
}

test.describe("Function Buttons Verification", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("http://127.0.0.1:8080/");
    await waitForAlpine(page);
  });

  test("1. Theme toggle button toggles dark state in Alpine app", async ({ page }) => {
    const themeBtn = page.locator('button:has-text("Theme")');
    await expect(themeBtn).toBeVisible();

    // Check initial state in Alpine component data (defaults to light theme)
    const initialDark = await page.evaluate(() => {
      const el = document.querySelector(".app");
      return (el.__x && el.__x.$data) ? el.__x.$data.dark : (window.Alpine ? Alpine.$data(el).dark : null);
    });
    expect(initialDark).toBe(false);

    // Click Theme button to toggle to dark
    await themeBtn.click();

    // Verify dark state toggled to true
    const toggledDark = await page.evaluate(() => {
      const el = document.querySelector(".app");
      return (el.__x && el.__x.$data) ? el.__x.$data.dark : (window.Alpine ? Alpine.$data(el).dark : null);
    });
    expect(toggledDark).toBe(true);

    // Click Theme button again to restore light
    await themeBtn.click();
    const restoredDark = await page.evaluate(() => {
      const el = document.querySelector(".app");
      return (el.__x && el.__x.$data) ? el.__x.$data.dark : (window.Alpine ? Alpine.$data(el).dark : null);
    });
    expect(restoredDark).toBe(false);
  });

  test("2. Sidebar navigation tabs switch content views", async ({ page }) => {
    const devicesTab = page.locator('.tab:has-text("Devices")');
    const mibsTab = page.locator('.tab:has-text("MIB Modules")');
    const historyTab = page.locator('.tab:has-text("History")');

    // Click MIB Modules tab
    await mibsTab.click();
    await expect(mibsTab).toHaveClass(/active/);
    await expect(devicesTab).not.toHaveClass(/active/);
    await expect(page.locator('button:has-text("Load All")')).toBeVisible();

    // Click History tab
    await historyTab.click();
    await expect(historyTab).toHaveClass(/active/);
    await expect(mibsTab).not.toHaveClass(/active/);

    // Switch back to Devices tab
    await devicesTab.click();
    await expect(devicesTab).toHaveClass(/active/);
    await expect(page.locator('button:has-text("Add Device")')).toBeVisible();
  });

  test("3. Device CRUD buttons (Add, Edit, Test, Select, Delete)", async ({ page }) => {
    // A. Add Device button
    const addBtn = page.locator('button:has-text("Add Device")');
    await addBtn.click();

    const modal = page.locator('.modal:has(h2:has-text("Add Device"))');
    await expect(modal).toBeVisible();

    const deviceName = "PW-Test-" + Date.now();
    await modal.locator('input[placeholder="My Router"]').fill(deviceName);
    await modal.locator('input[placeholder="169.254.128.1"]').fill("127.0.0.1");

    const saveBtn = modal.locator('button:has-text("Save")');
    await saveBtn.click();

    // Modal should close
    await expect(modal).not.toBeVisible();

    // Device card should appear in the list
    const card = page.locator(`.device-card:has-text("${deviceName}")`);
    await expect(card).toBeVisible();

    // B. Select Device button / card interaction
    await card.click();
    await expect(card).toHaveClass(/selected/);

    // Verify Target in status bar updates
    const targetStatus = page.locator('text=/Target:.*127\\.0\\.0\\.1:161/');
    await expect(targetStatus).toBeVisible();

    // Verify Start Walk button becomes enabled
    const startWalkBtn = page.locator('button:has-text("Start Walk")');
    await expect(startWalkBtn).toBeEnabled();

    // C. Test Device button
    const testBtn = card.locator('button:has-text("Test")');
    await testBtn.click();
    const toast = page.locator(".toast");
    await expect(toast).toBeVisible();

    // D. Edit Device button
    const editBtn = card.locator('button:has-text("Edit")');
    await editBtn.click();

    const editModal = page.locator('.modal:has(h2:has-text("Edit Device"))');
    await expect(editModal).toBeVisible();

    const updatedName = deviceName + "-edited";
    await editModal.locator('input[placeholder="My Router"]').fill(updatedName);
    await editModal.locator('button:has-text("Save")').click();
    await expect(editModal).not.toBeVisible();

    const updatedCard = page.locator(`.device-card:has-text("${updatedName}")`);
    await expect(updatedCard).toBeVisible();

    // E. Delete Device button (handle window.confirm)
    page.on("dialog", async (dialog) => {
      await dialog.accept();
    });

    const delBtn = updatedCard.locator('button:has-text("Del")');
    await delBtn.click();

    // Verify card is removed
    await expect(updatedCard).not.toBeVisible();
  });

  test("4. MIB Modules functional buttons (Refresh, Load All, Load Dir)", async ({ page }) => {
    // Navigate to MIB Modules tab
    await page.locator('.tab:has-text("MIB Modules")').click();

    const refreshBtn = page.locator('button:has-text("Refresh")');
    await expect(refreshBtn).toBeVisible();
    await refreshBtn.click();

    const toast = page.locator(".toast");
    await expect(toast).toContainText("MIB list refreshed");

    const loadAllBtn = page.locator('button:has-text("Load All")');
    await expect(loadAllBtn).toBeVisible();

    // Load from directory button
    const loadDirBtn = page.locator('.form-group button:has-text("Load")');
    await expect(loadDirBtn).toBeVisible();
  });

  test("5. Walk toolbar button states & Export modal buttons", async ({ page }) => {
    const startWalkBtn = page.locator('button:has-text("Start Walk")');
    const stopWalkBtn = page.locator('button:has-text("Stop")');
    const exportBtn = page.locator('button:has-text("Export")');
    const copyToolbarBtn = page.getByRole("button", { name: "Copy", exact: true });

    // Initial button states
    await expect(stopWalkBtn).toBeDisabled();
    await expect(exportBtn).toBeDisabled();
    await expect(copyToolbarBtn).toBeDisabled();

    // Test Export modal behavior by populating mock results
    await page.evaluate(() => {
      const el = document.querySelector(".app");
      const app = (el.__x && el.__x.$data) ? el.__x.$data : Alpine.$data(el);
      app.walkSessionId = "test-session";
      app.exportContent = "Test Export Content Preview";
      app.results = [{ oid: "1.3.6.1.2.1.1.1.0", name: "sysDescr", type: "DisplayString", value: "Test Router", index: "0" }];
    });

    // Now Export and Copy toolbar buttons should be enabled
    await expect(exportBtn).toBeEnabled();
    await expect(copyToolbarBtn).toBeEnabled();

    // Mock the export API endpoint for the session
    await page.route("**/api/walk/export/*", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          success: true,
          content: "Test Export Content Preview",
          message: "Export successful"
        })
      });
    });

    // Click Export button
    await exportBtn.click();

    // Export modal should open with preview
    const exportModal = page.locator('.modal:has(h2:has-text("Export Walk Results"))');
    await expect(exportModal).toBeVisible();
    await expect(exportModal.locator(".export-preview")).toContainText("Test Export Content Preview");

    // Verify Export modal action buttons
    const closeBtn = exportModal.locator('button:has-text("Close")');
    const copyExportBtn = exportModal.locator('button:has-text("Copy to Clipboard")');
    const downloadBtn = exportModal.locator('button:has-text("Download .txt")');

    await expect(closeBtn).toBeVisible();
    await expect(copyExportBtn).toBeVisible();
    await expect(downloadBtn).toBeVisible();

    // Click Close button to dismiss modal
    await closeBtn.click();
    await expect(exportModal).not.toBeVisible();
  });

  test("6. Keyboard shortcut Escape dismisses active modals", async ({ page }) => {
    // Open Add Device modal
    await page.locator('button:has-text("Add Device")').click();
    const modal = page.locator('.modal:has(h2:has-text("Add Device"))');
    await expect(modal).toBeVisible();

    // Press Escape key
    await page.keyboard.press("Escape");
    await expect(modal).not.toBeVisible();
  });
});


