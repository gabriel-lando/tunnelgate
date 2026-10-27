<script lang="ts">
	import Icon from './Icon.svelte';
	import RouteRow from './RouteRow.svelte';
	import { dashboard, sortRoutes, tunnelSummary } from '#lib/dashboard.svelte.ts';
	import { t } from '#lib/i18n/index.svelte.ts';
	import { settings } from '#lib/settings.svelte.ts';
	import type { Route, Tunnel } from '#lib/types.ts';

	let {
		tunnel,
		ontoggle,
		onclone,
		onremove,
		onblockall,
		onundo
	}: {
		tunnel: Tunnel;
		ontoggle: (route: Route) => void;
		onclone: (route: Route) => void;
		onremove: (route: Route) => void;
		onblockall: () => void;
		onundo: () => void;
	} = $props();

	const routes = $derived(sortRoutes(tunnel.routes, settings.prefs.order));
	const up = $derived(tunnel.status === 'healthy' || tunnel.status === 'degraded');
	const busy = $derived(!!dashboard.pending[`tunnel:${tunnel.id}`]);
	const details = $derived(tunnelSummary(tunnel));
</script>

<section class="overflow-hidden rounded-xl border border-line bg-surface">
	<div class="flex items-center gap-2.5 py-3 pr-2 pl-4 sm:gap-3 sm:py-4 sm:pr-5 sm:pl-5">
		<span class="size-2 shrink-0 rounded-full {up ? 'bg-ok' : 'bg-down'}"></span>
		<div class="min-w-0 flex-1">
			<h2 class="truncate text-[15px] font-semibold">{tunnel.name}</h2>
			<p class="text-[12.5px] text-muted sm:text-[13px]" title={t('tunnel.connections', { count: tunnel.connections })}>
				{details}
			</p>
		</div>
		{#if tunnel.can_undo && tunnel.remote_managed}
			<button
				type="button"
				disabled={busy}
				class="flex size-9 items-center justify-center rounded-lg border border-line text-muted hover:bg-surface-2 disabled:opacity-50"
				aria-label={t('tunnel.undo')}
				title={t('tunnel.undo')}
				onclick={onundo}><Icon name="undo" size={16} /></button
			>
		{/if}
		<button
			type="button"
			disabled={busy}
			class="h-9 rounded-lg border border-line px-3 text-[13px] font-medium text-danger-ink hover:bg-surface-2 disabled:opacity-50 sm:h-8"
			onclick={onblockall}>{t('tunnel.blockAll')}</button
		>
	</div>
	{#if !tunnel.remote_managed}
		<p class="border-t border-line bg-surface-2 px-5 py-2 text-[12.5px] text-muted">{t('tunnel.local')}</p>
	{/if}
	{#each routes as route (route.hostname + (route.path ?? ''))}
		<RouteRow
			{route}
			editable={tunnel.remote_managed}
			busy={!!dashboard.pending[route.hostname]}
			ontoggle={() => ontoggle(route)}
			onclone={() => onclone(route)}
			onremove={() => onremove(route)}
		/>
	{/each}
</section>
