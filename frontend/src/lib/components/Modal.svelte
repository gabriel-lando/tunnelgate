<script lang="ts">
	import type { Snippet } from 'svelte';
	import Icon from './Icon.svelte';
	import { t } from '#lib/i18n/index.svelte.ts';

	let {
		open,
		title,
		labelId,
		role = 'dialog',
		width = 'max-w-[560px]',
		onclose,
		children,
		footer
	}: {
		open: boolean;
		title: string;
		labelId: string;
		role?: 'dialog' | 'alertdialog';
		width?: string;
		onclose: () => void;
		children: Snippet;
		footer?: Snippet;
	} = $props();

	let dialog = $state<HTMLDialogElement>();

	$effect(() => {
		if (!dialog) return;
		if (open && !dialog.open) dialog.showModal();
		if (!open && dialog.open) dialog.close();
	});
</script>

<dialog
	bind:this={dialog}
	{role}
	aria-labelledby={labelId}
	{onclose}
	oncancel={(e) => {
		e.preventDefault();
		onclose();
	}}
	class="m-auto max-h-[90dvh] w-[calc(100%-2rem)] {width} overflow-hidden rounded-2xl border border-line bg-surface p-0 text-ink shadow-2xl"
>
	{#if open}
		<div class="flex max-h-[90dvh] flex-col">
			<header class="flex items-start gap-3 border-b border-line py-4 pr-4 pl-6">
				<h2 id={labelId} class="flex-1 pt-1 text-lg font-semibold">{title}</h2>
				<button
					type="button"
					class="flex size-9 items-center justify-center rounded-lg text-muted hover:bg-surface-2"
					aria-label={t('common.close')}
					onclick={onclose}
				>
					<Icon name="close" />
				</button>
			</header>
			<div class="flex-1 overflow-y-auto px-6 py-5">
				{@render children()}
			</div>
			{#if footer}
				<footer class="flex flex-wrap justify-end gap-2.5 border-t border-line px-6 py-4">
					{@render footer()}
				</footer>
			{/if}
		</div>
	{/if}
</dialog>
