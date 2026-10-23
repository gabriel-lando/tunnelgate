import { describe, expect, it } from 'vitest';
import { filterTunnels, sortRoutes, splitColumns, summarize } from '../src/lib/dashboard.svelte.ts';
import type { Route, State, Tunnel } from '../src/lib/types.ts';

const route = (hostname: string, blocked = false, service = 'http://x:1'): Route => ({
	hostname,
	service,
	path: null,
	zone: 'example.com',
	blocked,
	wildcard: false,
	critical: false,
	managed: true,
	can_block: true,
	block_disabled_reason: null,
	origin_request: {}
});

const tunnel = (name: string, routes: Route[]): Tunnel => ({
	id: name,
	name,
	status: 'healthy',
	connections: 1,
	remote_managed: true,
	can_undo: false,
	routes
});

const state: State = {
	tunnels: [
		tunnel('apps', [route('git.example.com'), route('vault.example.com', true)]),
		tunnel('media', [route('jellyfin.example.com', false, 'http://jellyfin:8096')])
	],
	zones: [],
	generated_at: 0
};

describe('dashboard helpers', () => {
	it('summarizes counts', () => {
		expect(summarize(state)).toEqual({ tunnels: 2, routes: 3, blocked: 1 });
		expect(summarize(null)).toEqual({ tunnels: 0, routes: 0, blocked: 0 });
	});

	it('filters by hostname, service and tunnel name', () => {
		expect(filterTunnels(state.tunnels, 'vault').map((t) => t.routes.length)).toEqual([1]);
		expect(filterTunnels(state.tunnels, 'jellyfin:8096')[0]?.name).toBe('media');
		expect(filterTunnels(state.tunnels, 'APPS')[0]?.routes.length).toBe(2);
		expect(filterTunnels(state.tunnels, '')).toBe(state.tunnels);
		expect(filterTunnels(state.tunnels, 'nothing')).toEqual([]);
	});

	it('sorts alphabetically without mutating', () => {
		const routes = [route('z.example.com'), route('a.example.com')];
		expect(sortRoutes(routes, 'alpha').map((r) => r.hostname)).toEqual(['a.example.com', 'z.example.com']);
		expect(sortRoutes(routes, 'ingress')).toBe(routes);
		expect(routes[0]?.hostname).toBe('z.example.com');
	});
});

describe('splitColumns', () => {
	const sized = (name: string, count: number) =>
		tunnel(
			name,
			Array.from({ length: count }, (_, i) => route(`r${i}.${name}.example.com`))
		);

	it('puts each card in the shortest column, so a tall card leaves no gap', () => {
		const [a, b, c] = [sized('a', 7), sized('b', 11), sized('c', 2)];
		const names = splitColumns([a, b, c], 2).map((col) => col.map((t) => t.name));
		expect(names).toEqual([['a', 'c'], ['b']]);
	});

	it('keeps the original order in a single column', () => {
		const items = [sized('a', 3), sized('b', 1)];
		expect(splitColumns(items, 1)).toEqual([items]);
		expect(splitColumns([], 2)).toEqual([[], []]);
	});
});
