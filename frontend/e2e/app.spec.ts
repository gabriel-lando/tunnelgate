import { expect, test, type Page, type Route as PwRoute } from '@playwright/test';

const ME = {
	username: 'gabriel',
	name: 'Gabriel Lando',
	groups: ['HomeAdmins'],
	csrf_token: 'csrf-e2e',
	expires_at: 4102444800
};

const route = (hostname: string, extra: Record<string, unknown> = {}) => ({
	hostname,
	service: 'http://svc:80',
	path: null,
	zone: 'example.com',
	blocked: false,
	wildcard: false,
	critical: false,
	managed: true,
	can_block: true,
	block_disabled_reason: null,
	origin_request: {},
	...extra
});

const STATE = {
	tunnels: [
		{
			id: '11111111-1111-4111-8111-111111111111',
			name: 'nikita-apps',
			status: 'healthy',
			connections: 4,
			replicas: 1,
			versions: ['2026.9.1'],
			remote_managed: true,
			can_undo: true,
			routes: [
				route('git.example.com', { service: 'http://gitea:3000' }),
				route('vault.example.com', {
					service: 'https://vaultwarden:443',
					blocked: true,
					origin_request: { noTLSVerify: true }
				}),
				route('*.apps.example.com', { wildcard: true }),
				route('other.elsewhere.org', { zone: null, can_block: false, block_disabled_reason: 'no_zone_access' })
			]
		},
		{
			id: '33333333-3333-4333-8333-333333333333',
			name: 'auth',
			status: 'healthy',
			connections: 8,
			replicas: 2,
			versions: ['2026.10.0', '2026.9.1'],
			remote_managed: true,
			can_undo: false,
			routes: [route('auth.example.com', { critical: true, service: 'https://swag-ext:443' })]
		}
	],
	zones: [{ id: 'a'.repeat(32), name: 'example.com' }],
	generated_at: 1
};

type Call = { url: string; body: unknown; headers: Record<string, string> };

async function mockApi(page: Page, opts: { me?: number } = {}): Promise<Call[]> {
	const calls: Call[] = [];
	await page.route('**/api/**', async (r: PwRoute) => {
		const req = r.request();
		const url = new URL(req.url()).pathname;
		if (req.method() === 'POST') calls.push({ url, body: req.postDataJSON(), headers: req.headers() });
		if (url === '/api/me') {
			if (opts.me === 403)
				return r.fulfill({ status: 403, json: { error: 'forbidden', reason: 'group', username: 'guest' } });
			return r.fulfill({ json: ME });
		}
		if (url === '/api/state') return r.fulfill({ json: STATE });
		if (url === '/api/kill-all')
			return r.fulfill({
				json: { ok: true, message: '', blocked: ['git.example.com'], skipped: ['other.elsewhere.org'] }
			});
		if (url === '/api/about')
			return r.fulfill({
				json: {
					version: '0.1.0',
					commit: 'abc',
					cloudflare_ok: true,
					token_status: 'active',
					token_expires_on: null,
					zones: ['example.com']
				}
			});
		if (url === '/api/routes/block') {
			const body = req.postDataJSON() as { hostname: string; confirm_critical: boolean };
			if (body.hostname === 'auth.example.com' && !body.confirm_critical)
				return r.fulfill({ status: 409, json: { detail: 'critical', confirm: true } });
		}
		return r.fulfill({ json: { ok: true, message: 'new.example.com', blocked: [], skipped: [] } });
	});
	await page.route('**/auth/login', (r) => r.fulfill({ status: 200, body: 'login page' }));
	return calls;
}

test('dashboard lists tunnels and toggles a route with CSRF', async ({ page }) => {
	const calls = await mockApi(page);
	await page.goto('/');
	await expect(page.getByRole('heading', { name: 'nikita-apps' })).toBeVisible();
	await expect(page.getByText('2 tunnels · 5 routes · 1 blocked')).toBeVisible();
	await page.getByRole('switch', { name: 'Block git.example.com' }).click();
	await expect.poll(() => calls.length).toBe(1);
	expect(calls[0]?.url).toBe('/api/routes/block');
	expect(calls[0]?.body).toEqual({ hostname: 'git.example.com', blocked: true, confirm_critical: false });
	expect(calls[0]?.headers['x-csrf-token']).toBe('csrf-e2e');
	await expect(page.getByRole('switch', { name: /other\.elsewhere\.org/ })).toBeDisabled();
	await expect(page.getByRole('switch', { name: /\*\.apps\.example\.com/ })).toBeEnabled();
});

test('critical routes and kill all ask for confirmation', async ({ page }) => {
	const calls = await mockApi(page);
	await page.goto('/');
	await page.getByRole('switch', { name: 'Block auth.example.com' }).click();
	await expect(page.getByRole('alertdialog')).toContainText('critical');
	expect(calls).toHaveLength(0);
	await page.getByRole('button', { name: 'Block anyway' }).click();
	await expect
		.poll(() => calls.at(-1)?.body)
		.toEqual({ hostname: 'auth.example.com', blocked: true, confirm_critical: true });

	await page.getByRole('button', { name: 'Kill all' }).filter({ visible: true }).click();
	await page.getByRole('button', { name: 'Block everything' }).click();
	await expect.poll(() => calls.at(-1)?.url).toBe('/api/kill-all');
	await expect(page.getByText('1 routes are still reachable: other.elsewhere.org')).toBeVisible();
});

test('remove requires typing the exact hostname', async ({ page, isMobile }) => {
	const calls = await mockApi(page);
	await page.goto('/');
	const row = page.locator('div', { hasText: /^git\.example\.com/ }).first();
	if (isMobile) {
		await page.getByRole('button', { name: 'More actions for git.example.com' }).click();
		await page.getByRole('menuitem', { name: 'Remove route' }).click();
	} else {
		await row.hover();
		await page.getByRole('button', { name: 'Remove route' }).first().click();
	}
	const submit = page.getByRole('button', { name: 'Remove route' }).last();
	await expect(submit).toBeDisabled();
	await page.getByRole('textbox').fill('git.example');
	await expect(submit).toBeDisabled();
	await page.getByRole('textbox').fill('git.example.com');
	await submit.click();
	await expect.poll(() => calls.at(-1)?.url).toBe('/api/tunnels/11111111-1111-4111-8111-111111111111/routes/remove');
	expect(calls.at(-1)?.body).toEqual({ hostname: 'git.example.com', path: null, confirm: 'git.example.com' });
});

test('clone validates input and sends the edited route', async ({ page, isMobile }) => {
	const calls = await mockApi(page);
	await page.goto('/');
	if (isMobile) {
		await page.getByRole('button', { name: 'More actions for vault.example.com' }).click();
		await page.getByRole('menuitem', { name: 'Clone route' }).click();
	} else {
		await page.getByRole('button', { name: 'Clone route' }).nth(1).click();
	}
	const dialog = page.getByRole('dialog');
	await expect(dialog).toContainText('From vault.example.com in nikita-apps');
	await dialog.getByLabel('Hostname').fill('bad_name');
	await dialog.getByRole('button', { name: 'Create route' }).click();
	await expect(dialog).toContainText('Use letters, digits and hyphens only.');
	expect(calls).toHaveLength(0);
	await dialog.getByLabel('Hostname').fill('vault-test');
	await dialog.getByRole('button', { name: 'Create route' }).click();
	await expect.poll(() => calls.at(-1)?.url).toContain('/routes/clone');
	expect(calls.at(-1)?.body).toMatchObject({
		source_hostname: 'vault.example.com',
		subdomain: 'vault-test',
		service: 'https://vaultwarden:443',
		origin_request: { noTLSVerify: true }
	});
});

test('authenticated but unauthorized users see the denied page without redirect loops', async ({ page }) => {
	await mockApi(page, { me: 403 });
	const loginHits: string[] = [];
	page.on('request', (r) => {
		if (r.url().includes('/auth/login')) loginHits.push(r.url());
	});
	await page.goto('/');
	await expect(page.getByRole('heading', { name: 'Access denied' })).toBeVisible();
	await expect(page.getByText('guest')).toBeVisible();
	await expect(page).toHaveURL(/\/denied$/);
	await page.waitForTimeout(500);
	expect(loginHits).toHaveLength(0);
});

test('settings switch theme and language', async ({ page }) => {
	await mockApi(page);
	await page.goto('/settings');
	await page.getByRole('radio', { name: 'Light' }).click();
	await expect(page.locator('html')).not.toHaveClass(/dark/);
	await page.getByRole('radio', { name: 'Dark' }).click();
	await expect(page.locator('html')).toHaveClass(/dark/);
	await page.getByLabel('Language').selectOption('pt-BR');
	await expect(page.getByRole('heading', { name: 'Configurações' }).first()).toBeAttached();
	await page.reload();
	await expect(page.locator('html')).toHaveClass(/dark/);
	await expect(page.locator('html')).toHaveAttribute('lang', 'pt-BR');
});

test('screenshots for visual review', async ({ page }, info) => {
	await mockApi(page);
	for (const scheme of ['dark', 'light'] as const) {
		await page.emulateMedia({ colorScheme: scheme });
		await page.goto('/');
		await expect(page.getByRole('heading', { name: 'nikita-apps' })).toBeVisible();
		await page.screenshot({ path: info.outputPath(`dashboard-${scheme}.png`), fullPage: true });
	}
});

test('route menu is not clipped by its card and behaves like a menu', async ({ page, isMobile }) => {
	test.skip(!isMobile, 'the overflow menu is mobile only');
	await mockApi(page);
	await page.goto('/');
	// Last route of its card: the menu extends past the card's bottom edge.
	await page.getByRole('button', { name: 'More actions for other.elsewhere.org' }).click();
	const remove = page.getByRole('menuitem', { name: 'Remove route' });
	await expect(remove).toBeVisible();
	const box = (await remove.boundingBox())!;
	const hit = await page.evaluate(
		([x, y]) => document.elementFromPoint(x!, y!)?.closest('[role=menuitem]')?.textContent ?? '',
		[box.x + box.width / 2, box.y + box.height / 2]
	);
	expect(hit).toContain('Remove route');

	await page.getByRole('button', { name: 'More actions for git.example.com' }).click();
	await expect(page.getByRole('menu')).toHaveCount(1);
	await page.keyboard.press('Escape');
	await expect(page.getByRole('menu')).toHaveCount(0);
});
