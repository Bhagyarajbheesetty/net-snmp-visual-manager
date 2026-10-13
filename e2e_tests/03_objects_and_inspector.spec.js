const { test, expect } = require("@playwright/test");

async function waitForAlpine(page) {
  await page.waitForFunction(() => window.Alpine && window.Alpine.version);
}

test.describe("3. MIB Objects & Inspector QA Suite", () => {
  test.beforeEach(async ({ page, request }) => {
    // Ensure PROXIM-MIB is loaded
    await request.post("http://127.0.0.1:8080/api/mibs/load", {
      data: { module_name: "PROXIM-MIB" }
    });
    await page.goto("/");
    await waitForAlpine(page);
  });

  test("3.1 Search objects and auto-import OID & Type into controls", async ({ page }) => {
    // Select real test device first while on Devices tab
    const deviceCard = page.locator('.device-card:has-text("192.168.10.40")').first();
    await deviceCard.click();

    const objectsTab = page.locator('.tab:has-text("Objects")');
    await objectsTab.click();

    // Search for a specific object
    const searchInput = page.locator('input[x-model="objectSearch"]');
    await expect(searchInput).toBeVisible();
    await searchInput.fill("sysMgmtCfgCommit");
    await page.waitForTimeout(600);

    const objectCard = page.locator('.obj-card:has-text("sysMgmtCfgCommit")').first();
    await expect(objectCard).toBeVisible({ timeout: 6000 });

    // Click object card
    await objectCard.click();

    // Verify Target OID is imported with numeric OID
    const oidInput = page.locator('input[x-model="walkFrom"]');
    await expect(oidInput).toHaveValue("1.3.6.1.4.1.841.1.1.2.1.4.2.0");

    // Toast indicates selection
    const toast = page.locator('.toast');
    await expect(toast).toBeVisible();
    await expect(toast).toContainText("sysMgmtCfgCommit");

    // Open SET modal to verify detected type and blank value
    const setBtn = page.locator('.toolbar button:has-text("SET")');
    await setBtn.click();
    const setModal = page.locator('.modal:has(h2:has-text("SNMP SET Operation"))');
    await expect(setModal).toBeVisible();

    const targetOidInModal = setModal.locator('input[x-model="setForm.oid"]');
    await expect(targetOidInModal).toHaveValue("1.3.6.1.4.1.841.1.1.2.1.4.2.0");

    const proposedValueInput = setModal.locator('input[x-model="setForm.value"]');
    await expect(proposedValueInput).toHaveValue("");

    // Dismiss SET modal
    await setModal.locator('button:has-text("Cancel")').click();
    await expect(setModal).not.toBeVisible();
  });
});
