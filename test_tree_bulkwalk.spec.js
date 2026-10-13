const { test, expect } = require("@playwright/test");

async function waitForAlpine(page) {
  await page.waitForFunction(() => window.Alpine && window.Alpine.version);
}

test.describe("MIB Tree View and Right-Click BulkWalk Verification", () => {
  test.beforeEach(async ({ page, request }) => {
    // Ensure PROXIM-MIB is loaded
    await request.post("http://127.0.0.1:8080/api/mibs/load", {
      data: { module_name: "PROXIM-MIB" }
    });
    await page.goto("http://127.0.0.1:8080/");
    await waitForAlpine(page);
  });

  test("1. Switch to MIB Tree tab and verify tree hierarchy renders", async ({ page }) => {
    const treeTab = page.locator('.tab:has-text("MIB Tree")');
    await expect(treeTab).toBeVisible();
    await treeTab.click();

    // Verify tree mount has rendered nodes
    const proximNode = page.locator('.tree-node-row:has-text("proxim")');
    await expect(proximNode).toBeVisible({ timeout: 5000 });

    // Verify enterprise (841) proxim label matches the visual design
    await expect(proximNode).toContainText("(841)");
    await expect(proximNode).toContainText("proxim");
  });

  test("2. Left-click tree node selects and populates Target OID", async ({ page }) => {
    const treeTab = page.locator('.tab:has-text("MIB Tree")');
    await treeTab.click();

    const proximNode = page.locator('.tree-node-row:has-text("proxim")');
    await proximNode.click();

    // Target OID should be set to 1.3.6.1.4.1.841
    const targetOidInput = page.locator('input[x-model="walkFrom"]');
    await expect(targetOidInput).toHaveValue("1.3.6.1.4.1.841");
  });

  test("3. Right-click node opens context menu and triggers BulkWalk Subtree", async ({ page }) => {
    // Select device
    const deviceCard = page.locator('.device-card:has-text("192.168.10.40")');
    await deviceCard.click();

    // Switch to MIB Tree tab
    const treeTab = page.locator('.tab:has-text("MIB Tree")');
    await treeTab.click();

    // Right-click on proxim node
    const proximNode = page.locator('.tree-node-row:has-text("proxim")');
    await proximNode.click({ button: "right" });

    // Verify context menu appears
    const contextMenu = page.locator(".context-menu");
    await expect(contextMenu).toBeVisible();
    await expect(contextMenu).toContainText("BulkWalk Subtree");
    await expect(contextMenu).toContainText("Walk Subtree");
    await expect(contextMenu).toContainText("SNMP GET");

    // Click BulkWalk Subtree option
    const bulkWalkItem = contextMenu.locator('.context-menu-item:has-text("BulkWalk Subtree")');
    await bulkWalkItem.click();

    // Verify Walk begins running with live results
    const statusDot = page.locator(".status-dot");
    await expect(statusDot).toHaveClass(/status-(running|completed)/, { timeout: 8000 });

    // Verify at least one result varbind arrived from enterprise 841
    const resultRow = page.locator("table tbody tr").first();
    await expect(resultRow).toBeVisible({ timeout: 8000 });
  });
});
