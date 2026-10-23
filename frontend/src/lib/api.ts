import type { About, CloneRequest, Denied, Me, OperationResult, State } from './types';

export class ApiError extends Error {
	constructor(
		public status: number,
		message: string,
		public needsConfirm = false,
		public notBlocked: string[] = []
	) {
		super(message);
	}
}

export type MeResult = { kind: 'ok'; me: Me } | { kind: 'denied'; denied: Denied } | { kind: 'anonymous' };

let csrfToken = '';

export function setCsrfToken(token: string): void {
	csrfToken = token;
}

export function loginUrl(): string {
	return '/auth/login';
}

async function request<T>(method: 'GET' | 'POST', path: string, body?: unknown): Promise<T> {
	const headers: Record<string, string> = { Accept: 'application/json' };
	if (method === 'POST') {
		headers['Content-Type'] = 'application/json';
		headers['X-CSRF-Token'] = csrfToken;
	}
	let resp: Response;
	try {
		resp = await fetch(path, {
			method,
			headers,
			credentials: 'same-origin',
			cache: 'no-store',
			redirect: 'error',
			body: body === undefined ? undefined : JSON.stringify(body)
		});
	} catch {
		throw new ApiError(0, 'network');
	}
	if (resp.status === 401) {
		window.location.assign(loginUrl());
		throw new ApiError(401, 'unauthenticated');
	}
	let data: unknown;
	try {
		data = await resp.json();
	} catch {
		data = null;
	}
	if (!resp.ok) {
		const detail =
			data && typeof data === 'object' && 'detail' in data
				? String((data as { detail: unknown }).detail)
				: resp.statusText;
		const body = (data && typeof data === 'object' ? data : {}) as Record<string, unknown>;
		const list = (v: unknown) => (Array.isArray(v) ? v.map(String) : []);
		throw new ApiError(resp.status, detail, 'confirm' in body, [...list(body['failed']), ...list(body['skipped'])]);
	}
	return data as T;
}

export async function fetchMe(): Promise<MeResult> {
	let resp: Response;
	try {
		resp = await fetch('/api/me', { credentials: 'same-origin', cache: 'no-store', redirect: 'error' });
	} catch {
		throw new ApiError(0, 'network');
	}
	if (resp.status === 401) return { kind: 'anonymous' };
	if (resp.status === 403) return { kind: 'denied', denied: (await resp.json()) as Denied };
	if (!resp.ok) throw new ApiError(resp.status, resp.statusText);
	const me = (await resp.json()) as Me;
	setCsrfToken(me.csrf_token);
	return { kind: 'ok', me };
}

export const api = {
	state: (refresh = false) => request<State>('GET', `/api/state${refresh ? '?refresh=true' : ''}`),
	about: () => request<About>('GET', '/api/about'),
	setBlocked: (hostname: string, blocked: boolean, confirmCritical = false) =>
		request<OperationResult>('POST', '/api/routes/block', {
			hostname,
			blocked,
			confirm_critical: confirmCritical
		}),
	blockTunnel: (tunnelId: string) =>
		request<OperationResult>('POST', `/api/tunnels/${encodeURIComponent(tunnelId)}/block-all`, { confirm: true }),
	killAll: () => request<OperationResult>('POST', '/api/kill-all', { confirm: true }),
	clone: (tunnelId: string, body: CloneRequest) =>
		request<OperationResult>('POST', `/api/tunnels/${encodeURIComponent(tunnelId)}/routes/clone`, body),
	remove: (tunnelId: string, hostname: string, path: string | null, confirm: string) =>
		request<OperationResult>('POST', `/api/tunnels/${encodeURIComponent(tunnelId)}/routes/remove`, {
			hostname,
			path,
			confirm
		}),
	undo: (tunnelId: string) =>
		request<OperationResult>('POST', `/api/tunnels/${encodeURIComponent(tunnelId)}/undo`, { confirm: true })
};
