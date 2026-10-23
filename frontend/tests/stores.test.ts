import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const json = (status: number, body: unknown) =>
	new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } });

const state = {
	tunnels: [
		{
			id: 't1',
			name: 'apps',
			status: 'healthy',
			connections: 1,
			remote_managed: true,
			can_undo: true,
			routes: [
				{
					hostname: 'a.example.com',
					service: 'http://a:1',
					path: null,
					zone: 'example.com',
					blocked: false,
					wildcard: false,
					critical: false,
					managed: true,
					can_block: true,
					block_disabled_reason: null,
					origin_request: {}
				}
			]
		}
	],
	zones: [{ id: 'z', name: 'example.com' }],
	generated_at: 1
};

describe('stores', () => {
	beforeEach(() => {
		vi.useFakeTimers();
		vi.stubGlobal('location', { assign: vi.fn() });
	});
	afterEach(() => {
		vi.useRealTimers();
		vi.unstubAllGlobals();
		vi.resetModules();
	});

	it('dashboard loads state and runs actions with toasts', async () => {
		const { dashboard } = await import('../src/lib/dashboard.svelte.ts');
		const { toasts } = await import('../src/lib/toasts.svelte.ts');
		const ok = { ok: true, message: 'b.example.com', blocked: ['a.example.com'], skipped: ['x.other.org'] };
		const fetchMock = vi.fn((url: string) =>
			Promise.resolve(url.startsWith('/api/state') ? json(200, state) : json(200, ok))
		);
		vi.stubGlobal('fetch', fetchMock);

		await dashboard.load();
		expect(dashboard.state?.tunnels[0]?.name).toBe('apps');
		const tunnel = dashboard.state!.tunnels[0]!;
		const route = tunnel.routes[0]!;

		expect(await dashboard.setBlocked(route, true)).toBe(true);
		expect(await dashboard.blockTunnel(tunnel)).toBe(true);
		expect(await dashboard.killAll()).toBe(true);
		expect(await dashboard.undo(tunnel)).toBe(true);
		expect(await dashboard.remove(tunnel, route, 'a.example.com')).toBe(true);
		const body = {
			source_hostname: 'a.example.com',
			source_path: null,
			subdomain: 'b',
			zone_id: 'z',
			service: 'http://b:1',
			path: null,
			origin_request: {},
			create_blocked: false
		};
		expect(await dashboard.clone(tunnel, body)).toBe(true);
		expect(toasts.items.some((t) => t.kind === 'error' && t.message.includes('x.other.org'))).toBe(true);
		vi.advanceTimersByTime(10_000);
		expect(toasts.items.length).toBe(0);
	});

	it('dashboard uses the state returned by a block instead of refreshing', async () => {
		const { dashboard } = await import('../src/lib/dashboard.svelte.ts');
		const blockedState = structuredClone(state);
		blockedState.tunnels[0]!.routes[0]!.blocked = true;
		const fetchMock = vi.fn((url: string) =>
			Promise.resolve(
				url.startsWith('/api/state')
					? json(200, state)
					: json(200, { ok: true, message: '', blocked: ['a.example.com'], skipped: [], state: blockedState })
			)
		);
		vi.stubGlobal('fetch', fetchMock);

		await dashboard.load();
		expect(await dashboard.setBlocked(dashboard.state!.tunnels[0]!.routes[0]!, true)).toBe(true);
		expect(dashboard.state?.tunnels[0]?.routes[0]?.blocked).toBe(true);
		expect(fetchMock.mock.calls.filter(([url]) => url.startsWith('/api/state'))).toHaveLength(1);
	});

	it('dashboard sends dialog errors to the callback instead of a toast', async () => {
		const { dashboard } = await import('../src/lib/dashboard.svelte.ts');
		const { toasts } = await import('../src/lib/toasts.svelte.ts');
		vi.stubGlobal(
			'fetch',
			vi.fn(() => Promise.resolve(json(409, { detail: 'already used' })))
		);
		const tunnel = state.tunnels[0]! as never;
		const onError = vi.fn();
		const before = toasts.items.length;

		expect(await dashboard.clone(tunnel, {} as never, onError)).toBe(false);
		expect(await dashboard.remove(tunnel, state.tunnels[0]!.routes[0]! as never, 'x', onError)).toBe(false);
		expect(onError).toHaveBeenCalledTimes(2);
		expect(onError.mock.calls[0]![0]).toContain('already used');
		expect(toasts.items.length).toBe(before);
	});

	it('dashboard reports failures as error toasts and rethrows confirmations', async () => {
		const { dashboard } = await import('../src/lib/dashboard.svelte.ts');
		const { toasts } = await import('../src/lib/toasts.svelte.ts');
		vi.stubGlobal(
			'fetch',
			vi.fn(() => Promise.resolve(json(502, { detail: 'Cloudflare API error' })))
		);
		await dashboard.load();
		expect(dashboard.error).toBe('Cloudflare API error');
		const route = state.tunnels[0]!.routes[0]!;
		expect(await dashboard.setBlocked(route as never, true)).toBe(false);
		expect(toasts.items.at(-1)?.kind).toBe('error');

		vi.stubGlobal(
			'fetch',
			vi.fn(() => Promise.resolve(json(409, { detail: 'critical', confirm: true })))
		);
		await expect(dashboard.setBlocked(route as never, true)).rejects.toMatchObject({ needsConfirm: true });
	});

	it('session classifies the current user', async () => {
		const { session } = await import('../src/lib/session.svelte.ts');
		vi.stubGlobal(
			'fetch',
			vi.fn(() => Promise.resolve(json(403, { error: 'forbidden', reason: 'mfa', username: 'g' })))
		);
		expect(await session.init('/')).toBe('denied');
		expect(session.denied?.reason).toBe('mfa');
		vi.stubGlobal(
			'fetch',
			vi.fn(() => Promise.reject(new TypeError('offline')))
		);
		expect(await session.init('/')).toBe('offline');
		vi.stubGlobal(
			'fetch',
			vi.fn(() => Promise.resolve(json(401, {})))
		);
		expect(await session.init('/signed-out')).toBe('anonymous');
		expect(window.location.assign).not.toHaveBeenCalled();
		expect(await session.init('/')).toBe('anonymous');
		expect(window.location.assign).toHaveBeenCalledWith('/auth/login');
	});

	it('settings persist and apply theme and language', async () => {
		const store = new Map<string, string>();
		vi.stubGlobal('localStorage', {
			getItem: (k: string) => store.get(k) ?? null,
			setItem: (k: string, v: string) => void store.set(k, v)
		});
		vi.stubGlobal('matchMedia', () => ({ matches: true, addEventListener: () => {} }));
		window.matchMedia = (() => ({ matches: true, addEventListener: () => {} })) as never;
		const { settings } = await import('../src/lib/settings.svelte.ts');
		const { i18n } = await import('../src/lib/i18n/index.svelte.ts');
		settings.init();
		expect(document.documentElement.classList.contains('dark')).toBe(true);
		settings.update({ theme: 'light', language: 'pt-BR' });
		expect(document.documentElement.classList.contains('dark')).toBe(false);
		expect(i18n.lang).toBe('pt-BR');
		expect(store.get('tunnelgate.theme')).toBe('light');
		expect(JSON.parse(store.get('tunnelgate.prefs')!).language).toBe('pt-BR');
	});
});
