const { test, expect } = require("@playwright/test");

async function waitForAlpine(page) {
  await page.waitForFunction(() => window.Alpine && window.Alpine.version);
}

test.describe("5 Phases Enhanced Features Verification", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("http://127.0.0.1:8080/");
    await waitForAlpine(page);
  });

  test("Phase 2: MIB File Loading, Drag-Drop, Unload & Reload controls", async ({ page }) => {
    // 1. Switch to MIB Modules tab
    await page.locator('.tab:has-text("MIB Modules")').click();

    // 2. Verify Load MIB, Unload, Reload, Unload All buttons exist
    const loadBtn = page.locator('button:has-text("Browse / Load MIB")');
    const unloadBtn = page.locator('button:has-text("Unload")').first();
    const reloadBtn = page.locator('button:has-text("Reload")');
    const unloadAllBtn = page.locator('button:has-text("Unload All")');

    await expect(loadBtn).toBeVisible();
    await expect(unloadBtn).toBeVisible();
    await expect(reloadBtn).toBeVisible();
    await expect(unloadAllBtn).toBeVisible();

    // Initially with no MIB selected, Unload and Reload are disabled
    await expect(unloadBtn).toBeDisabled();
    await expect(reloadBtn).toBeDisabled();

    // 3. Load PXM-SNMP.txt from path
    await page.locator('input[x-model="mibSourceDir"]').fill("C:\\net-snmp\\share\\snmp\\mibs\\PXM-SNMP.txt");
    await page.locator('.form-group button:has-text("Load")').click();

    const toast = page.locator(".toast");
    await expect(toast).toBeVisible();

    // 4. Select PROXIM-MIB from the list
    const proximItem = page.locator('.mib-item:has-text("PROXIM-MIB")');
    await expect(proximItem).toBeVisible();
    await proximItem.click();

    // Now Unload and Reload should be enabled
    await expect(unloadBtn).toBeEnabled();
    await expect(reloadBtn).toBeEnabled();

    // 5. Test Unload button: removes from application while source is safe
    await unloadBtn.click();
    await expect(toast).toContainText("unloaded from application context");

    // 6. Reload PROXIM-MIB again for further phase tests
    await page.locator('input[x-model="mibSourceDir"]').fill("C:\\net-snmp\\share\\snmp\\mibs\\PXM-SNMP.txt");
    await page.locator('.form-group button:has-text("Load")').click();
    await expect(toast).toBeVisible();
  });

  test("Phase 3: MIB Object Discovery and Inspector", async ({ page }) => {
    // 1. Switch to Objects tab
    const objectsTab = page.locator('.tab:has-text("Objects")');
    await expect(objectsTab).toBeVisible();
    await objectsTab.click();

    // 2. Search for wirelessIfPropertiesRadioStatus
    const searchInput = page.locator('input[placeholder*="Search objects"]');
    await searchInput.fill("wirelessIfPropertiesRadioStatus");

    // 3. Object card should be visible
    const objCard = page.locator('.obj-card:has-text("wirelessIfPropertiesRadioStatus")');
    await expect(objCard).toBeVisible();

    // 4. Click to select object -> sets Target OID in toolbar
    await objCard.click();
    const oidInput = page.locator('input[x-model="walkFrom"]');
    await expect(oidInput).toHaveValue(/(wirelessIfPropertiesRadioStatus|1\.3\.6\.1\.4\.1\.841)/);
  });

  test("Phase 4: Type-Aware SNMP GET and SET operations on real device", async ({ page }) => {
    // 1. Ensure target device (192.168.10.40) is selected
    const deviceCard = page.locator('.device-card:has-text("192.168.10.40")');
    await expect(deviceCard).toBeVisible();
    await deviceCard.click();

    // 2. Test SNMP GET button
    const oidInput = page.locator('input[x-model="walkFrom"]');
    await oidInput.fill("PROXIM-MIB::wirelessIfPropertiesRadioStatus.1");

    const getBtn = page.locator('button:has-text("GET")');
    await expect(getBtn).toBeEnabled();
    await getBtn.click();

    const toast = page.locator(".toast");
    await expect(toast).toContainText("GET succeeded");

    // Verify row appears in results table
    const resultRow = page.locator('table tbody tr:has-text("wirelessIfPropertiesRadioStatus.1")');
    await expect(resultRow).toBeVisible();

    // 3. Test SNMP SET button and modal
    const setBtn = page.locator('.toolbar button:has-text("SET")');
    await expect(setBtn).toBeEnabled();
    await setBtn.click();

    // SET Modal opens with confirmation
    const setModal = page.locator('.modal:has(h2:has-text("SNMP SET Operation"))');
    await expect(setModal).toBeVisible();

    // Fill proposed value: 1 (enable)
    await setModal.locator('input[placeholder*="1, 100"]').fill("1");

    // Click Execute SET
    await setModal.locator('button:has-text("Execute SET")').click();
    await expect(setModal).not.toBeVisible();
    await expect(toast).toContainText("SET successful");
  });

  test("Phase 5: Full Walk and Export to txt file", async ({ page }) => {
    // 1. Select device 192.168.10.40
    const deviceCard = page.locator('.device-card:has-text("192.168.10.40")');
    await deviceCard.click();

    // 2. Set From OID to 1.3.6.1.4.1.841
    const oidInput = page.locator('input[x-model="walkFrom"]');
    await oidInput.fill("1.3.6.1.4.1.841");

    // 3. Select BulkWalk mode and Start Walk
    await page.locator('select[x-model="walkMode"]').selectOption("bulk");
    const startWalkBtn = page.locator('button:has-text("Start Walk")');
    await startWalkBtn.click();

    // 4. Verify walk runs and produces varbinds
    await expect(page.locator('table tbody tr').first()).toBeVisible({ timeout: 15000 });
    const stopBtn = page.locator('button:has-text("Stop")');
    if (await stopBtn.isEnabled()) {
      await stopBtn.click(); // Stop after receiving rows to allow instant export
    }

    // 5. Click Export button
    const exportBtn = page.locator('.toolbar button:has-text("Export")');
    await expect(exportBtn).toBeEnabled({ timeout: 10000 });
    await exportBtn.click();

    // 6. Export Modal opens
    const exportModal = page.locator('.modal:has(h2:has-text("Export Walk Results"))');
    await expect(exportModal).toBeVisible();
    await expect(exportModal.locator(".export-preview")).toContainText("[SNMP Agent]");

    // 7. Verify Download .txt button
    const downloadBtn = exportModal.locator('button:has-text("Download .txt")');
    await expect(downloadBtn).toBeVisible();

    await exportModal.locator('button:has-text("Close")').click();
    await expect(exportModal).not.toBeVisible();
  });
});
