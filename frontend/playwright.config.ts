import { defineConfig, devices } from '@playwright/test';

const executablePath = process.env.PLAYWRIGHT_CHROMIUM_PATH || undefined;
const args = process.env.PLAYWRIGHT_CHROMIUM_ARGS ? process.env.PLAYWRIGHT_CHROMIUM_ARGS.split(' ') : [];

export default defineConfig({
	testDir: 'e2e',
	fullyParallel: true,
	forbidOnly: !!process.env.CI,
	retries: process.env.CI ? 1 : 0,
	reporter: process.env.CI ? 'list' : [['list']],
	use: {
		baseURL: 'http://127.0.0.1:4173',
		trace: 'retain-on-failure',
		launchOptions: { executablePath, args }
	},
	webServer: { command: 'node e2e/server.mjs', url: 'http://127.0.0.1:4173/', reuseExistingServer: !process.env.CI },
	projects: [
		{ name: 'desktop', use: { ...devices['Desktop Chrome'], viewport: { width: 1280, height: 900 } } },
		{ name: 'mobile', use: { ...devices['Pixel 7'] } }
	]
});
