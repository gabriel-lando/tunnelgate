<script lang="ts">
	import { resolve } from '$app/paths';
	import { onMount } from 'svelte';
	import { ApiError } from '#lib/api.ts';
	import CloneDialog from '#lib/components/CloneDialog.svelte';
	import ConfirmDialog from '#lib/components/ConfirmDialog.svelte';
	import Icon from '#lib/components/Icon.svelte';
	import Logo from '#lib/components/Logo.svelte';
	import RemoveDialog from '#lib/components/RemoveDialog.svelte';
	import TunnelCard from '#lib/components/TunnelCard.svelte';
	import { dashboard, filterTunnels, summarize } from '#lib/dashboard.svelte.ts';
	import { t } from '#lib/i18n/index.svelte.ts';
	import { session } from '#lib/session.svelte.ts';
	import type { CloneRequest, Route, Tunnel } from '#lib/types.ts';

	type Confirm =
		| { kind: 'kill' }
		| { kind: 'tunnel'; tunnel: Tunnel }
		| { kind: 'critical'; route: Route }
		| { kind: 'undo'; tunnel: Tunnel };

	let query = $state('');
	let searchOpen = $state(false);
	let online = $state(true);
	let confirm = $state<Confirm | null>(null);
	let cloneTarget = $state<{ tunnel: Tunnel; route: Route } | null>(null);
	let removeTarget = $state<{ tunnel: Tunnel; route: Route } | null>(null);
	let dialogError = $state<string | null>(null);
	let pull = $state(0);

	const counts = $derived(summarize(dashboard.state));
	const tunnels = $derived(filterTunnels(dashboard.state?.tunnels ?? [], query));
	const initials = $derived(
		(session.me?.name ?? '?')
			.split(/\s+/)
			.map((p: string) => p[0] ?? '')
			.join('')
			.slice(0, 2)
			.toUpperCase()
	);

	onMount(() => {
		online = navigator.onLine;
		const up = () => {
			online = true;
			void dashboard.load(true);
		};
		const down = () => (online = false);
		window.addEventListener('online', up);
		window.addEventListener('offline', down);
		if (online) void dashboard.load();
		return () => {
			window.removeEventListener('online', up);
			window.removeEventListener('offline', down);
		};
	});

	// Pull-to-refresh: only when the page is scrolled to the top.
	let startY: number | null = null;
	function touchStart(e: TouchEvent) {
		startY = window.scrollY <= 0 ? (e.touches[0]?.clientY ?? null) : null;
	}
	function touchMove(e: TouchEvent) {
		if (startY === null) return;
		pull = Math.max(0, Math.min(96, (e.touches[0]?.clientY ?? startY) - startY));
	}
	function touchEnd() {
		if (pull >= 72 && !dashboard.loading) void dashboard.load(true);
		pull = 0;
		startY = null;
	}

	async function toggle(route: Route) {
		const block = !route.blocked;
		if (block && route.critical) {
			confirm = { kind: 'critical', route };
			return;
		}
		try {
			await dashboard.setBlocked(route, block);
		} catch (err) {
			if (err instanceof ApiError && err.needsConfirm) confirm = { kind: 'critical', route };
		}
	}

	async function runConfirm() {
		const c = confirm;
		confirm = null;
		if (!c) return;
		if (c.kind === 'kill') await dashboard.killAll();
		else if (c.kind === 'tunnel') await dashboard.blockTunnel(c.tunnel);
		else if (c.kind === 'undo') await dashboard.undo(c.tunnel);
		else await dashboard.setBlocked(c.route, true, true).catch(() => false);
	}

	const confirmText = $derived.by(() => {
		const c = confirm;
		if (!c) return { title: '', body: '', submit: '', danger: true };
		if (c.kind === 'kill')
			return {
				title: t('confirm.killAll.title'),
				body: t('confirm.killAll.body'),
				submit: t('confirm.killAll.submit'),
				danger: true
			};
		if (c.kind === 'tunnel')
			return {
				title: t('confirm.blockTunnel.title', { tunnel: c.tunnel.name }),
				body: t('confirm.blockTunnel.body'),
				submit: t('confirm.blockTunnel.submit'),
				danger: true
			};
		if (c.kind === 'undo')
			return {
				title: t('confirm.undo.title', { tunnel: c.tunnel.name }),
				body: t('confirm.undo.body'),
				submit: t('confirm.undo.submit'),
				danger: false
			};
		return {
			title: t('confirm.critical.title'),
			body: t('confirm.critical.body', { host: c.route.hostname }),
			submit: t('confirm.critical.submit'),
			danger: true
		};
	});

	async function submitClone(body: CloneRequest) {
		if (!cloneTarget) return;
		dialogError = null;
		const ok = await dashboard.clone(cloneTarget.tunnel, body, (m) => (dialogError = m));
		if (ok) cloneTarget = null;
	}

	async function submitRemove(typed: string) {
		if (!removeTarget) return;
		dialogError = null;
		const ok = await dashboard.remove(removeTarget.tunnel, removeTarget.route, typed, (m) => (dialogError = m));
		if (ok) removeTarget = null;
	}

	function closeDialogs() {
		cloneTarget = null;
		removeTarget = null;
		dialogError = null;
	}
</script>

<svelte:window ontouchstart={touchStart} ontouchmove={touchMove} ontouchend={touchEnd} />

<div class="min-h-dvh bg-bg pb-28 sm:pb-10">
	<header class="sticky top-0 z-10 border-b border-line bg-surface">
		<div class="mx-auto flex h-14 max-w-[1200px] items-center gap-1 pr-3 pl-4 sm:h-16 sm:gap-4 sm:px-6">
			<Logo />
			<div class="flex-1"></div>
			<label
				class="hidden h-9 w-72 items-center gap-2 rounded-lg border border-line bg-bg px-3 text-muted focus-within:border-accent sm:flex"
			>
				<Icon name="search" size={16} />
				<input
					type="search"
					bind:value={query}
					placeholder={t('nav.search')}
					aria-label={t('nav.search')}
					class="min-w-0 flex-1 bg-transparent text-ink outline-none placeholder:text-muted"
				/>
			</label>
			<button
				type="button"
				class="flex size-11 items-center justify-center rounded-lg text-muted sm:hidden"
				aria-label={t('nav.search')}
				aria-expanded={searchOpen}
				onclick={() => (searchOpen = !searchOpen)}><Icon name="search" size={20} /></button
			>
			<button
				type="button"
				class="hidden size-10 items-center justify-center rounded-lg border border-line text-muted hover:bg-surface-2 sm:flex"
				aria-label={t('nav.refresh')}
				disabled={dashboard.loading}
				onclick={() => dashboard.load(true)}
			>
				<span class={dashboard.loading ? 'animate-spin' : ''}><Icon name="refresh" /></span>
			</button>
			<a
				href={resolve('/settings')}
				class="flex size-11 items-center justify-center rounded-lg text-muted hover:bg-surface-2 sm:size-10 sm:border sm:border-line"
				aria-label={t('nav.settings')}><Icon name="settings" size={20} /></a
			>
			<span
				role="img"
				aria-label={t('nav.signedInAs', { name: session.me?.name ?? '' })}
				class="hidden size-8 items-center justify-center rounded-full bg-surface-2 text-xs font-semibold sm:flex"
				>{initials}</span
			>
		</div>
		{#if searchOpen}
			<div class="px-4 pb-3 sm:hidden">
				<input
					type="search"
					bind:value={query}
					placeholder={t('nav.search')}
					aria-label={t('nav.search')}
					class="h-11 w-full rounded-lg border border-line bg-bg px-3 text-[15px] text-ink outline-none focus:border-accent"
				/>
			</div>
		{/if}
	</header>

	{#if pull > 0}
		<div class="flex justify-center text-[13px] text-muted" style="height: {pull}px; align-items: flex-end">
			<span class="pb-2">{pull >= 72 ? t('dashboard.pullToRefresh') : ''}</span>
		</div>
	{/if}

	<main class="mx-auto flex max-w-[1200px] flex-col gap-4 px-4 py-5 sm:gap-6 sm:px-6 sm:py-7">
		<div class="flex flex-wrap items-end justify-between gap-4">
			<div>
				<h1 class="text-[22px] font-semibold tracking-tight sm:text-2xl">{t('dashboard.title')}</h1>
				{#if dashboard.state}
					<p class="mt-0.5 text-[13px] text-muted sm:mt-1 sm:text-sm">{t('dashboard.summary', counts)}</p>
				{/if}
			</div>
			<button
				type="button"
				class="hidden h-10 items-center gap-2 rounded-lg bg-danger px-4 font-semibold text-white disabled:opacity-50 sm:flex"
				disabled={!dashboard.state || !!dashboard.pending['kill-all']}
				onclick={() => (confirm = { kind: 'kill' })}
			>
				<Icon name="power" size={16} stroke={2.25} />{t('dashboard.killAll')}
			</button>
		</div>

		{#if !online || session.offline}
			<div class="flex items-center gap-3 rounded-xl border border-line bg-surface px-4 py-3 text-muted">
				<Icon name="wifiOff" />{t('dashboard.offline')}
			</div>
		{:else if dashboard.error}
			<div
				class="flex flex-wrap items-center gap-3 rounded-xl border border-danger-ink/30 bg-surface px-4 py-3 text-danger-ink"
			>
				<span class="flex-1">{t('dashboard.loadError', { message: dashboard.error })}</span>
				<button
					type="button"
					class="h-9 rounded-lg border border-line px-3 font-medium"
					onclick={() => dashboard.load(true)}>{t('common.retry')}</button
				>
			</div>
		{:else if !dashboard.state}
			<p class="text-muted">{t('dashboard.loading')}</p>
		{:else if dashboard.state.tunnels.length === 0}
			<p class="text-muted">{t('dashboard.empty')}</p>
		{:else if tunnels.length === 0}
			<p class="text-muted">{t('dashboard.noMatches')}</p>
		{/if}

		{#if online && dashboard.state && !dashboard.error}
			<div class="grid grid-cols-1 items-start gap-4 sm:gap-5 lg:grid-cols-2">
				{#each tunnels as tunnel (tunnel.id)}
					<TunnelCard
						{tunnel}
						ontoggle={toggle}
						onclone={(route) => (cloneTarget = { tunnel, route })}
						onremove={(route) => (removeTarget = { tunnel, route })}
						onblockall={() => (confirm = { kind: 'tunnel', tunnel })}
						onundo={() => (confirm = { kind: 'undo', tunnel })}
					/>
				{/each}
			</div>
		{/if}
	</main>

	<div
		class="fixed inset-x-0 bottom-0 z-10 border-t border-line bg-surface px-4 pt-3 pb-[max(1.5rem,env(safe-area-inset-bottom))] sm:hidden"
	>
		<button
			type="button"
			class="flex h-12 w-full items-center justify-center gap-2 rounded-[10px] bg-danger text-[15px] font-semibold text-white disabled:opacity-50"
			disabled={!dashboard.state || !!dashboard.pending['kill-all']}
			onclick={() => (confirm = { kind: 'kill' })}
		>
			<Icon name="power" stroke={2.25} />{t('dashboard.killAll')}
		</button>
	</div>
</div>

<ConfirmDialog
	open={confirm !== null}
	title={confirmText.title}
	body={confirmText.body}
	submitLabel={confirmText.submit}
	danger={confirmText.danger}
	onconfirm={runConfirm}
	onclose={() => (confirm = null)}
/>

<CloneDialog
	open={cloneTarget !== null}
	tunnel={cloneTarget?.tunnel ?? null}
	route={cloneTarget?.route ?? null}
	zones={dashboard.state?.zones ?? []}
	busy={cloneTarget ? !!dashboard.pending[`tunnel:${cloneTarget.tunnel.id}`] : false}
	error={dialogError}
	onsubmit={submitClone}
	onclose={closeDialogs}
/>

<RemoveDialog
	open={removeTarget !== null}
	tunnel={removeTarget?.tunnel ?? null}
	route={removeTarget?.route ?? null}
	busy={removeTarget ? !!dashboard.pending[removeTarget.route.hostname] : false}
	error={dialogError}
	onsubmit={submitRemove}
	onclose={closeDialogs}
/>
