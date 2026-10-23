<script lang="ts">
	import Modal from './Modal.svelte';
	import { t } from '#lib/i18n/index.svelte.ts';
	import type { Route, Tunnel } from '#lib/types.ts';

	let {
		open,
		tunnel,
		route,
		busy,
		error = null,
		onsubmit,
		onclose
	}: {
		open: boolean;
		tunnel: Tunnel | null;
		route: Route | null;
		busy: boolean;
		error?: string | null;
		onsubmit: (confirm: string) => void;
		onclose: () => void;
	} = $props();

	let typed = $state('');

	$effect(() => {
		if (open) typed = '';
	});

	const matches = $derived(!!route && typed.trim() === route.hostname);
</script>

<Modal {open} title={t('remove.title')} labelId="remove-title" role="alertdialog" width="max-w-[480px]" {onclose}>
	{#if route && tunnel}
		<form
			id="remove-form"
			class="flex flex-col gap-4"
			onsubmit={(e) => {
				e.preventDefault();
				if (matches) onsubmit(typed.trim());
			}}
		>
			<p class="text-muted">{t('remove.body', { tunnel: tunnel.name })}</p>
			<label for="remove-confirm" class="flex flex-col gap-2">
				<span>
					{t('remove.confirmBefore')}
					<span class="rounded-md bg-surface-2 px-1.5 py-px font-mono text-[13px] font-semibold select-all"
						>{route.hostname}</span
					>
					{t('remove.confirmAfter')}
				</span>
				<input
					id="remove-confirm"
					bind:value={typed}
					autocomplete="off"
					autocapitalize="off"
					spellcheck="false"
					class="h-10 rounded-lg border border-line-strong bg-bg px-3 font-mono text-[13px] text-ink outline-none focus:border-accent"
				/>
			</label>
		</form>
	{/if}
	{#snippet footer()}
		{#if error}
			<p role="alert" class="w-full rounded-lg bg-danger-soft px-3.5 py-2.5 text-[13px] text-danger-ink">{error}</p>
		{/if}
		<button
			type="button"
			class="h-10 rounded-lg border border-line-strong px-4 font-medium hover:bg-surface-2"
			onclick={onclose}>{t('common.cancel')}</button
		>
		<button
			type="submit"
			form="remove-form"
			disabled={!matches || busy}
			class="h-10 rounded-lg bg-danger px-4 font-semibold text-white disabled:cursor-not-allowed disabled:opacity-45"
			>{t('remove.submit')}</button
		>
	{/snippet}
</Modal>
