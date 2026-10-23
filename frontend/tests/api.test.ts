import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { api, ApiError, fetchMe } from '../src/lib/api.ts';

const json = (status: number, body: unknown) =>
	new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } });

describe('api client', () => {
	const assign = vi.fn();
	beforeEach(() => {
		vi.stubGlobal('location', { assign });
	});
	afterEach(() => {
		vi.unstubAllGlobals();
		assign.mockReset();
	});

	it('reports anonymous, denied and signed-in sessions', async () => {
		vi.stubGlobal('fetch', vi.fn().mockResolvedValueOnce(json(401, {})));
		expect(await fetchMe()).toEqual({ kind: 'anonymous' });
		vi.stubGlobal(
			'fetch',
			vi.fn().mockResolvedValueOnce(json(403, { error: 'forbidden', reason: 'group', username: 'x' }))
		);
		expect((await fetchMe()).kind).toBe('denied');
		vi.stubGlobal(
			'fetch',
			vi
				.fn()
				.mockResolvedValueOnce(json(200, { username: 'g', name: 'G', groups: [], csrf_token: 'tok', expires_at: 1 }))
		);
		expect((await fetchMe()).kind).toBe('ok');
	});

	it('sends the CSRF token on mutations', async () => {
		vi.stubGlobal(
			'fetch',
			vi
				.fn()
				.mockResolvedValueOnce(
					json(200, { username: 'g', name: 'G', groups: [], csrf_token: 'tok-123', expires_at: 1 })
				)
		);
		await fetchMe();
		const fetchMock = vi.fn().mockResolvedValueOnce(json(200, { ok: true, message: '', blocked: [] }));
		vi.stubGlobal('fetch', fetchMock);
		await api.setBlocked('a.example.com', true);
		const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
		expect((init.headers as Record<string, string>)['X-CSRF-Token']).toBe('tok-123');
		expect(init.credentials).toBe('same-origin');
		expect(JSON.parse(init.body as string)).toEqual({
			hostname: 'a.example.com',
			blocked: true,
			confirm_critical: false
		});
	});

	it('redirects to login on 401 and surfaces errors', async () => {
		vi.stubGlobal('fetch', vi.fn().mockResolvedValueOnce(json(401, {})));
		await expect(api.state()).rejects.toBeInstanceOf(ApiError);
		expect(assign).toHaveBeenCalledWith('/auth/login');

		vi.stubGlobal('fetch', vi.fn().mockResolvedValueOnce(json(409, { detail: 'critical', confirm: true })));
		await expect(api.setBlocked('x.example.com', true)).rejects.toMatchObject({ status: 409, needsConfirm: true });

		vi.stubGlobal('fetch', vi.fn().mockRejectedValueOnce(new TypeError('offline')));
		await expect(api.killAll()).rejects.toMatchObject({ status: 0 });
	});

	it('encodes tunnel ids in paths', async () => {
		const fetchMock = vi.fn().mockResolvedValueOnce(json(200, { ok: true, message: '', blocked: [] }));
		vi.stubGlobal('fetch', fetchMock);
		await api.undo('../../x');
		expect(fetchMock.mock.calls[0]?.[0]).toBe('/api/tunnels/..%2F..%2Fx/undo');
	});
});
