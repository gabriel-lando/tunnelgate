<script lang="ts">
	import { toasts } from '#lib/toasts.svelte.ts';
	import { t } from '#lib/i18n/index.svelte.ts';
	import Icon from './Icon.svelte';
</script>

<div
	class="pointer-events-none fixed inset-x-0 bottom-24 z-50 flex flex-col items-center gap-2 px-4 sm:bottom-6"
	aria-live="polite"
	role="status"
>
	{#each toasts.items as toast (toast.id)}
		<div
			class="pointer-events-auto flex max-w-md items-center gap-3 rounded-xl border px-4 py-3 shadow-lg {toast.kind ===
			'error'
				? 'border-danger-ink/30 bg-surface text-danger-ink'
				: 'border-line bg-surface text-ink'}"
		>
			<span class="flex-1 text-sm">{toast.message}</span>
			<button type="button" class="text-muted" aria-label={t('common.close')} onclick={() => toasts.dismiss(toast.id)}
				><Icon name="close" size={16} /></button
			>
		</div>
	{/each}
</div>
