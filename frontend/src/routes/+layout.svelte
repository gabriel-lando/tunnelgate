<script lang="ts">
	import '../app.css';
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { page } from '$app/state';
	import { onMount, type Snippet } from 'svelte';
	import Toasts from '#lib/components/Toasts.svelte';
	import { session } from '#lib/session.svelte.ts';
	import { settings } from '#lib/settings.svelte.ts';
	import { t } from '#lib/i18n/index.svelte.ts';

	let { children }: { children: Snippet } = $props();

	const publicPages = new Set(['/denied', '/signed-out']);

	onMount(async () => {
		settings.init();
		const path = page.url.pathname;
		const result = await session.init(path);
		if (result === 'denied' && path !== '/denied') await goto(resolve('/denied'), { replaceState: true });
		if (result === 'ok' && publicPages.has(path)) await goto(resolve('/'), { replaceState: true });
	});
</script>

<svelte:head>
	<title>{t('app.name')}</title>
</svelte:head>

{#if session.ready && (session.me || session.offline || publicPages.has(page.url.pathname))}
	{@render children()}
{/if}

<Toasts />
