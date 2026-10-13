const { test, expect } = require("@playwright/test");

async function waitForAlpine(page) {
  await page.waitForFunction(() => window.Alpine && window.Alpine.version);
}

test.describe("2. MIB Modules & Tree View QA Suite", () => {
  test.beforeEach(async ({ page, request }) => {
    // Ensure IF-MIB is loaded
    await request.post("http://127.0.0.1:8080/api/mibs/load", {
      data: { module_name: "IF-MIB" }
    });
    await page.goto("/");
    await waitForAlpine(page);
  });

  test("2.1 MIB Modules tab buttons (Refresh, Load All, Browse)", async ({ page }) => {
    const mibsTab = page.locator('.tab:has-text("MIB Modules")');
    await mibsTab.click();

    // Verify action buttons exist and are clickable
    const refreshBtn = page.locator('div[x-show="sideTab===\'mibs\'"] button:has-text("Refresh")');
    const unloadAllBtn = page.locator('div[x-show="sideTab===\'mibs\'"] button:has-text("Unload All")');
    const browseBtn = page.locator('div[x-show="sideTab===\'mibs\'"] button:has-text("Browse / Load MIB")');

    await expect(refreshBtn).toBeVisible();
    await expect(unloadAllBtn).toBeVisible();
    await expect(browseBtn).toBeVisible();

    await refreshBtn.click();
    const toast = page.locator('.toast');
    await expect(toast).toBeVisible({ timeout: 5000 });

    // Verify IF-MIB module item exists
    const mibItem = page.locator('.mib-item:has-text("IF-MIB")').first();
    await expect(mibItem).toBeVisible();
  });

  test("2.2 MIB Tree renders hierarchy, search filter, and node left-click", async ({ page }) => {
    const treeTab = page.locator('.tab:has-text("MIB Tree")');
    await treeTab.click();

    // Verify interfaces 841 node rendered in tree
    const treeNode = page.locator('.tree-node-row:has-text("interfaces")');
    await expect(treeNode).toBeVisible({ timeout: 6000 });
    await expect(treeNode).toContainText("(2)");

    // Test Tree Search Input
    const searchInput = page.locator('input[x-model="treeSearch"]');
    await expect(searchInput).toBeVisible();
    await searchInput.fill("wirelessIf");
    await page.waitForTimeout(300);

    // Left-click on a tree node to populate Target OID
    await treeNode.click();
    const oidInput = page.locator('input[x-model="walkFrom"]');
    await expect(oidInput).toHaveValue(/1\.3\.6\.1\.4\.1\.841/);
  });

  test("2.3 MIB Tree right-click Context Menu and BulkWalk trigger", async ({ page }) => {
    // Select real test device 127.0.0.1 first
    const deviceCard = page.locator('.device-card:has-text("127.0.0.1")').first();
    await deviceCard.click();

    const treeTab = page.locator('.tab:has-text("MIB Tree")');
    await treeTab.click();

    const treeNode = page.locator('.tree-node-row:has-text("interfaces")');
    await expect(treeNode).toBeVisible({ timeout: 6000 });

    // Right-click interfaces node
    await treeNode.click({ button: "right" });

    // Verify context menu opens with required options
    const menu = page.locator(".context-menu");
    await expect(menu).toBeVisible();
    await expect(menu.locator('text=BulkWalk Subtree')).toBeVisible();
    await expect(menu.getByText('Walk Subtree', { exact: true })).toBeVisible();
    await expect(menu.locator('text=SNMP GET')).toBeVisible();
    await expect(menu.locator('text=SNMP SET')).toBeVisible();
    await expect(menu.locator('text=Copy Numeric OID')).toBeVisible();

    // Click BulkWalk Subtree
    const bulkWalkItem = menu.locator('.context-menu-item:has-text("BulkWalk Subtree")');
    await bulkWalkItem.click();

    // Context menu dismisses and walk starts
    await expect(menu).not.toBeVisible();
    const toast = page.locator(".toast");
    await expect(toast).toBeVisible();
    await expect(toast).toContainText("Starting BulkWalk");

    // Verify walk status becomes running and stop button is active
    const stopBtn = page.locator('.toolbar button:has-text("Stop")');
    await expect(stopBtn).toBeEnabled({ timeout: 5000 });

    // Stop walk cleanly
    await stopBtn.click();
    const statusDot = page.locator(".status-dot");
    await expect(statusDot).toHaveClass(/status-stopped/, { timeout: 8000 });
  });
});


