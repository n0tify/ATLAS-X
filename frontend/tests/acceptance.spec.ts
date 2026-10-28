import { test, expect } from '@playwright/test';

test.describe('Acceptance Workflows', () => {
  test.beforeEach(async ({ page }) => {
    const timestamp = Date.now();
    const username = `accuser${timestamp}`;
    await page.goto('/register');
    await page.fill('input#username', username);
    await page.fill('input#password', 'testpass123');
    await page.fill('input#confirmPassword', 'testpass123');
    await page.click('button[type="submit"]');
    await page.waitForURL('**/dashboard', { timeout: 15000 });
    await expect(page.locator('h1')).toBeVisible({ timeout: 15000 });
  });

  test('dashboard loads', async ({ page }) => {
    await expect(page.locator('h1')).toBeVisible();
  });

  test('task creation and detail', async ({ page }) => {
    await page.goto('/tasks/create');
    await expect(page.locator('text=Create Research Task')).toBeVisible();
    await page.fill('input#title', 'Acceptance Task');
    await page.fill('textarea#goal', 'Acceptance workflow verification');
    await page.click('button:has-text("Create Task")');
    await page.waitForURL(/\/tasks\/\d+/, { timeout: 15000 });
    await expect(page.locator('h1:has-text("Acceptance Task")')).toBeVisible();
    await expect(page.locator('text=Task Overview')).toBeVisible();
  });

  test('research playground tool execution', async ({ page }) => {
    await page.goto('/tasks/create');
    await page.fill('input#title', 'Playground Task');
    await page.fill('textarea#goal', 'Playground verification');
    await page.click('button:has-text("Create Task")');
    await page.waitForURL(/\/tasks\/\d+/, { timeout: 15000 });

    await page.goto('/playground');
    await expect(page.getByRole('heading', { name: 'Tools' })).toBeVisible({ timeout: 15000 });

    await page.locator('xpath=//h4[text()="text_statistics"]/ancestor::div[contains(@class,"glass-panel-elevated")][1]//button[contains(., "Select Tool")]').click();
    await page.locator('textarea').fill('hello world acceptance test');
    await page.click('button:has-text("Run Analysis")');
    await expect(page.getByText('succeeded', { exact: true })).toBeVisible({ timeout: 15000 });
  });

  test('provenance explorer loads', async ({ page }) => {
    await page.goto('/provenance');
    await expect(page.getByRole('heading', { name: 'Provenance Explorer' })).toBeVisible({ timeout: 15000 });
  });

  test('security center loads and verifies', async ({ page }) => {
    await page.goto('/security');
    await expect(page.getByRole('heading', { name: 'Security Center' })).toBeVisible({ timeout: 15000 });
    const verifyButton = page.locator('button:has-text("Verify Integrity"), button:has-text("Run Audit")').first();
    if (await verifyButton.isVisible()) {
      await verifyButton.click();
      await expect(page.getByText('CHAIN')).toBeVisible({ timeout: 15000 });
    }
  });

  test('benchmarks page loads', async ({ page }) => {
    await page.goto('/benchmarks');
    await expect(page.locator('text=Research Benchmarks')).toBeVisible({ timeout: 15000 });
    await expect(page.locator('button:has-text("Run Experiment")')).toBeVisible();
  });

  test('responsive no horizontal overflow', async ({ page }) => {
    for (const size of [{ width: 375, height: 667 }, { width: 768, height: 1024 }, { width: 1280, height: 720 }]) {
      await page.setViewportSize(size);
      await page.goto('/dashboard');
      await page.waitForLoadState('networkidle');
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1);
      expect(overflow).toBe(false);
    }
  });
});
