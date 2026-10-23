<script lang="ts">
	import Modal from './Modal.svelte';
	import { t } from '#lib/i18n/index.svelte.ts';

	let {
		open,
		title,
		body,
		submitLabel,
		danger = true,
		busy = false,
		onconfirm,
		onclose
	}: {
		open: boolean;
		title: string;
		body: string;
		submitLabel: string;
		danger?: boolean;
		busy?: boolean;
		onconfirm: () => void;
		onclose: () => void;
	} = $props();
</script>

<Modal {open} {title} labelId="confirm-title" role="alertdialog" width="max-w-[480px]" {onclose}>
	<p class="text-muted">{body}</p>
	{#snippet footer()}
		<button
			type="button"
			class="h-10 rounded-lg border border-line-strong px-4 font-medium hover:bg-surface-2"
			onclick={onclose}>{t('common.cancel')}</button
		>
		<button
			type="button"
			disabled={busy}
			class="h-10 rounded-lg px-4 font-semibold disabled:opacity-50 {danger
				? 'bg-danger text-white'
				: 'bg-accent text-[#18181b]'}"
			onclick={onconfirm}>{submitLabel}</button
		>
	{/snippet}
</Modal>
