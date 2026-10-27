import { expect, test, type Page } from '@playwright/test';
import { fileURLToPath } from 'node:url';

// Demo data for the documentation screenshots; not part of the E2E suite.
const OUT = fileURLToPath(new URL('../../docs/ui/', import.meta.url));

const route = (hostname: string, service: string, extra: Record<string, unknown> = {}) => ({
	hostname,
	service,
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

const tunnel = (n: string, name: string, replicas: number, versions: string[], routes: unknown[], canUndo = false) => ({
	id: `${n.repeat(8)}-${n.repeat(4)}-4${n.repeat(3)}-8${n.repeat(3)}-${n.repeat(12)}`,
	name,
	status: 'healthy',
	connections: replicas * 4,
	replicas,
	versions,
	remote_managed: true,
	can_undo: canUndo,
	routes
});

const STATE = {
	tunnels: [
		tunnel(
			'1',
			'edge-primary',
			2,
			['2026.10.0'],
			[
				route('sso.example.com', 'http://keycloak:8080', { critical: true }),
				route('wiki.example.com', 'http://bookstack:80'),
				route('photos.example.com', 'http://immich:2283', { blocked: true }),
				route('chat.example.com', 'http://matrix-synapse:8008'),
				route('ci.example.com', 'http://jenkins:8080', { blocked: true }),
				route('status.example.com', 'http://uptime-kuma:3001')
			],
			true
		),
		tunnel(
			'2',
			'edge-public',
			2,
			['2026.10.0', '2026.9.1'],
			[
				route('shop.example.com', 'http://storefront:3000'),
				route('api.example.com', 'http://api-gateway:9000'),
				route('*.review.example.com', 'http://review-apps:8080', { wildcard: true }),
				route('beta.example.com', 'http://beta-web:3000', { blocked: true })
			]
		),
		tunnel(
			'3',
			'sandbox',
			1,
			['2026.9.1'],
			[
				route('metrics.example.com', 'http://prometheus:9090'),
				route('lab.elsewhere.org', 'http://lab:8080', {
					zone: null,
					can_block: false,
					block_disabled_reason: 'no_zone_access'
				})
			]
		)
	],
	zones: [{ id: 'a'.repeat(32), name: 'example.com' }],
	generated_at: 1
};

const ME = { username: 'admin', name: 'Admin', groups: ['admins'], csrf_token: 'x', expires_at: 4102444800 };

async function mockApi(page: Page) {
	await page.route('**/api/**', (r) => {
		const url = new URL(r.request().url()).pathname;
		if (url === '/api/me') return r.fulfill({ json: ME });
		if (url === '/api/state') return r.fulfill({ json: STATE });
		return r.fulfill({ json: {} });
	});
}

test.use({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 2, colorScheme: 'dark' });

test('dashboard (desktop, dark)', async ({ page }) => {
	await mockApi(page);
	await page.goto('/');
	await expect(page.getByRole('heading', { name: 'edge-primary' })).toBeVisible();
	await page.screenshot({ path: `${OUT}dashboard-desktop-dark.png` });
});
