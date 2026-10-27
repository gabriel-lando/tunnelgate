import { api, ApiError } from './api';
import { t } from './i18n/index.svelte';
import { toasts } from './toasts.svelte';
import type { CloneRequest, OperationResult, Route, State, Tunnel } from './types';

export function errorMessage(err: unknown): string {
	if (err instanceof ApiError) return err.status === 0 ? t('error.network') : err.message;
	return err instanceof Error ? err.message : String(err);
}

export function sortRoutes(routes: Route[], order: 'ingress' | 'alpha'): Route[] {
	if (order === 'ingress') return routes;
	return [...routes].sort((a, b) => a.hostname.localeCompare(b.hostname));
}

export function filterTunnels(tunnels: Tunnel[], query: string): Tunnel[] {
	const q = query.trim().toLowerCase();
	if (!q) return tunnels;
	return tunnels
		.map((tn) => ({
			...tn,
			routes: tn.name.toLowerCase().includes(q)
				? tn.routes
				: tn.routes.filter((r) => r.hostname.includes(q) || (r.service ?? '').toLowerCase().includes(q))
		}))
		.filter((tn) => tn.routes.length > 0);
}

// Masonry layout: each card goes to the currently shortest column (height ~ header + one unit per route),
// so a tall card does not leave a gap under its neighbour as grid rows would.
export function splitColumns(tunnels: Tunnel[], count: number): Tunnel[][] {
	const columns: Tunnel[][] = Array.from({ length: count }, () => []);
	const heights: number[] = new Array<number>(count).fill(0);
	for (const tunnel of tunnels) {
		const i = heights.indexOf(Math.min(...heights));
		columns[i]!.push(tunnel);
		heights[i]! += 2 + tunnel.routes.length;
	}
	return columns;
}

export function summarize(state: State | null): { tunnels: number; routes: number; blocked: number } {
	const tunnels = state?.tunnels ?? [];
	const routes = tunnels.flatMap((tn) => tn.routes);
	return { tunnels: tunnels.length, routes: routes.length, blocked: routes.filter((r) => r.blocked).length };
}

/** e.g. "Healthy · 2 replicas · v2026.9.1 · v2026.8.0" */
export function tunnelSummary(tunnel: Tunnel): string {
	const parts = [t(`tunnel.status.${tunnel.status}`)];
	if (tunnel.replicas > 0) {
		parts.push(tunnel.replicas === 1 ? t('tunnel.replica') : t('tunnel.replicas', { count: tunnel.replicas }));
	}
	parts.push(...tunnel.versions.map((v) => `v${v}`));
	return parts.join(' · ');
}

export function notBlockedMessage(hosts: string[]): string {
	return t('toast.notBlocked', { count: hosts.length, hosts: hosts.join(', ') });
}

// A returned state saves a full refresh after the action.
interface Outcome {
	message: string | null;
	state?: State | null;
}

function reportBlocked(res: OperationResult): Outcome {
	if (res.skipped?.length) toasts.push(notBlockedMessage(res.skipped), 'error');
	return { message: t('toast.blockedMany', { count: res.blocked.length }), state: res.state };
}

class Dashboard {
	state = $state<State | null>(null);
	loading = $state(false);
	error = $state<string | null>(null);
	pending = $state<Record<string, boolean>>({});

	async load(refresh = false): Promise<void> {
		this.loading = true;
		try {
			this.state = await api.state(refresh);
			this.error = null;
		} catch (err) {
			this.error = errorMessage(err);
		} finally {
			this.loading = false;
		}
	}

	// onError shows errors in an open dialog: toasts would render behind it.
	private async run(
		key: string,
		action: () => Promise<Outcome>,
		onError?: (message: string) => void
	): Promise<boolean> {
		this.pending = { ...this.pending, [key]: true };
		try {
			const { message, state } = await action();
			if (message) toasts.push(message);
			if (state) {
				this.state = state;
				this.error = null;
			} else {
				await this.load(true);
			}
			return true;
		} catch (err) {
			if (err instanceof ApiError && err.needsConfirm) throw err;
			if (err instanceof ApiError && err.notBlocked.length > 0) {
				toasts.push(notBlockedMessage(err.notBlocked), 'error');
				await this.load(true);
				return false;
			}
			const message = t('error.generic', { message: errorMessage(err) });
			if (onError) onError(message);
			else toasts.push(message, 'error');
			return false;
		} finally {
			const { [key]: _, ...rest } = this.pending;
			this.pending = rest;
		}
	}

	setBlocked(route: Route, blocked: boolean, confirmCritical = false): Promise<boolean> {
		return this.run(route.hostname, async () => {
			const res = await api.setBlocked(route.hostname, blocked, confirmCritical);
			return { message: t(blocked ? 'toast.blocked' : 'toast.allowed', { host: route.hostname }), state: res.state };
		});
	}

	blockTunnel(tunnel: Tunnel): Promise<boolean> {
		return this.run(`tunnel:${tunnel.id}`, async () => reportBlocked(await api.blockTunnel(tunnel.id)));
	}

	killAll(): Promise<boolean> {
		return this.run('kill-all', async () => reportBlocked(await api.killAll()));
	}

	clone(tunnel: Tunnel, body: CloneRequest, onError?: (message: string) => void): Promise<boolean> {
		return this.run(
			`tunnel:${tunnel.id}`,
			async () => {
				const res = await api.clone(tunnel.id, body);
				return { message: t('toast.cloned', { host: res.message }) };
			},
			onError
		);
	}

	remove(tunnel: Tunnel, route: Route, confirm: string, onError?: (message: string) => void): Promise<boolean> {
		return this.run(
			route.hostname,
			async () => {
				await api.remove(tunnel.id, route.hostname, route.path, confirm);
				return { message: t('toast.removed', { host: route.hostname }) };
			},
			onError
		);
	}

	undo(tunnel: Tunnel): Promise<boolean> {
		return this.run(`tunnel:${tunnel.id}`, async () => {
			await api.undo(tunnel.id);
			return { message: t('toast.undone') };
		});
	}
}

export const dashboard = new Dashboard();
