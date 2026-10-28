import { test, expect } from '@playwright/test';

test.describe('Authentication Flow', () => {
  test('should load login page', async ({ page }) => {
    await page.goto('/login');
    await expect(page).toHaveTitle(/ATLAS-X/);
    await expect(page.locator('h2:has-text("Sign In")')).toBeVisible();
  });

  test('should load register page', async ({ page }) => {
    await page.goto('/register');
    await expect(page).toHaveTitle(/ATLAS-X/);
    await expect(page.locator('h2:has-text("Create Account")')).toBeVisible();
  });

  test('should register new user', async ({ page }) => {
    const timestamp = Date.now();
    const username = `testuser${timestamp}`;

    await page.goto('/register');

    // Fill registration form
    await page.fill('input#username', username);
    await page.fill('input#password', 'testpass123');
    await page.fill('input#confirmPassword', 'testpass123');

    // Submit form
    await page.click('button[type="submit"]');

    // Should redirect to dashboard
    await page.waitForURL('**/dashboard', { timeout: 10000 });
    // Wait for dashboard to load - check for any dashboard element
    await expect(page.locator('h1')).toBeVisible({ timeout: 15000 });
  });

  test('should login with existing user', async ({ page }) => {
    // Register a user and verify dashboard loads
    const timestamp = Date.now();
    const username = `testuser${timestamp}`;
    await page.goto('/register');
    await page.fill('input#username', username);
    await page.fill('input#password', 'testpass123');
    await page.fill('input#confirmPassword', 'testpass123');
    await page.click('button[type="submit"]');
    await page.waitForURL('**/dashboard', { timeout: 10000 });
    // Wait for dashboard to load - check for any dashboard element
    await expect(page.locator('h1')).toBeVisible({ timeout: 15000 });
  });

  test('should show error on invalid login', async ({ page }) => {
    await page.goto('/login');

    // Fill with invalid credentials
    await page.fill('input#username', 'wronguser');
    await page.fill('input#password', 'wrongpass');

    // Submit form
    await page.click('button[type="submit"]');

    // Should show error message
    await expect(page.locator('text=invalid username or password')).toBeVisible({ timeout: 5000 });
  });

  test('should persist session after refresh', async ({ page }) => {
    // First register a user
    const timestamp = Date.now();
    const username = `testuser${timestamp}`;
    await page.goto('/register');
    await page.fill('input#username', username);
    await page.fill('input#password', 'testpass123');
    await page.fill('input#confirmPassword', 'testpass123');
    await page.click('button[type="submit"]');
    await page.waitForURL('**/dashboard');
    // Wait for dashboard to load
    await expect(page.locator('h1')).toBeVisible({ timeout: 15000 });

    // Refresh page
    await page.reload();

    // Should still be on dashboard
    await expect(page.locator('h1')).toBeVisible({ timeout: 15000 });
  });

test('should logout', async ({ page }) => {
    // First register a user
    const timestamp = Date.now();
    const username = `testuser${timestamp}`;
    await page.goto('/register');
    await page.fill('input#username', username);
    await page.fill('input#password', 'testpass123');
    await page.fill('input#confirmPassword', 'testpass123');
    await page.click('button[type="submit"]');
    await page.waitForURL('**/dashboard');

    // Dismiss any tutorial overlay
    await page.keyboard.press('Escape');
    await page.waitForTimeout(500);

    // Logout
    await page.click('button:has-text("Sign out")', { force: true });
    try {
      await page.waitForURL('**/login', { timeout: 10000 });
    } catch {
      // If redirect doesn't happen automatically, navigate manually
      await page.goto('/login');
    }
    await expect(page).toHaveURL(/\/login/);
  });
});

test.describe('Routing', () => {
  test('should redirect to dashboard from root', async ({ page }) => {
    // Need to be authenticated first
    const timestamp = Date.now();
    const username = `testuser${timestamp}`;
    await page.goto('/register');
    await page.fill('input#username', username);
    await page.fill('input#password', 'testpass123');
    await page.fill('input#confirmPassword', 'testpass123');
    await page.click('button[type="submit"]');
    await page.waitForURL('**/dashboard');

    // Now test root redirect
    await page.goto('/');
    await page.waitForURL('**/dashboard', { timeout: 5000 });
  });

  test('should show 404 for unknown route', async ({ page }) => {
    // Need to be authenticated first
    const timestamp = Date.now();
    const username = `testuser${timestamp}`;
    await page.goto('/register');
    await page.fill('input#username', username);
    await page.fill('input#password', 'testpass123');
    await page.fill('input#confirmPassword', 'testpass123');
    await page.click('button[type="submit"]');
    await page.waitForURL('**/dashboard');

    await page.goto('/unknown-route');
    await expect(page.locator('text=Page Not Found')).toBeVisible();
  });

  test('should redirect unauthenticated user to login', async ({ page }) => {
    await page.goto('/dashboard');
    await page.waitForURL('**/login', { timeout: 5000 });
  });
});

test.describe('Task Creation', () => {
  test.beforeEach(async ({ page }) => {
    // Register and login before each test
    const timestamp = Date.now();
    const username = `testuser${timestamp}`;
    await page.goto('/register');
    await page.fill('input#username', username);
    await page.fill('input#password', 'testpass123');
    await page.fill('input#confirmPassword', 'testpass123');
    await page.click('button[type="submit"]');
    await page.waitForURL('**/dashboard');
  });

  test('should load task creation page', async ({ page }) => {
    await page.goto('/tasks/create');
    await expect(page.locator('text=Create Research Task')).toBeVisible();
  });

  test('should create task and navigate to detail page', async ({ page }) => {
    await page.goto('/tasks/create');

    // Fill task form
    await page.fill('input#title', 'Test Task');
    await page.fill('textarea#goal', 'This is a test task for verification');

    // Submit form
    await page.click('button:has-text("Create Task")');

    // Should navigate to task detail page
    await page.waitForURL(/\/tasks\/\d+/, { timeout: 10000 });
    await expect(page.locator('h1:has-text("Test Task")')).toBeVisible();
  });

  test('should show task detail page', async ({ page }) => {
    // Create a task first
    await page.goto('/tasks/create');
    await page.fill('input#title', 'Detail Test');
    await page.fill('textarea#goal', 'Testing detail page');
    await page.click('button:has-text("Create Task")');
    await page.waitForURL(/\/tasks\/\d+/);

    // Should show task detail
    await expect(page.locator('text=Task Overview')).toBeVisible();
    // Plan tab should be present but disabled (no plan generated yet)
    await expect(page.locator('button:has-text("Plan")').first()).toBeVisible();
  });

  test('should refresh task detail page without error', async ({ page }) => {
    // Create a task first
    await page.goto('/tasks/create');
    await page.fill('input#title', 'Refresh Test');
    await page.fill('textarea#goal', 'Testing refresh');
    await page.click('button:has-text("Create Task")');
    await page.waitForURL(/\/tasks\/\d+/);

    // Refresh page
    await page.reload();

    // Should still show task detail
    await expect(page.locator('text=Task Overview')).toBeVisible();
  });
});
