import { defineConfig, devices } from '@playwright/test';
import base from './playwright.config.ts';

// Regenerates docs/ui/*.png: pnpm build && pnpm screenshots
export default defineConfig({
	...base,
	testDir: 'screenshots',
	retries: 0,
	projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }]
});
