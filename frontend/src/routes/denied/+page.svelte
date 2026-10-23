<script lang="ts">
	import Icon from '#lib/components/Icon.svelte';
	import Logo from '#lib/components/Logo.svelte';
	import { t } from '#lib/i18n/index.svelte.ts';
	import { session } from '#lib/session.svelte.ts';

	const reason = $derived(session.denied?.reason ?? 'group');
</script>

<div class="flex min-h-dvh flex-col items-center justify-center gap-6 bg-bg px-4 py-12">
	<Logo />
	<main class="flex w-full max-w-[440px] flex-col gap-5 rounded-2xl border border-line bg-surface p-8">
		<span class="flex size-12 items-center justify-center rounded-full bg-danger-soft text-danger-ink">
			<Icon name="lock" size={24} />
		</span>
		<div>
			<h1 class="text-[22px] font-semibold tracking-tight">{t('denied.title')}</h1>
			<p class="mt-2 text-muted">{t('denied.body')}</p>
		</div>
		{#if session.denied}
			<dl class="grid grid-cols-[auto_1fr] gap-x-3 gap-y-2 rounded-[10px] bg-surface-2 px-4 py-3.5 text-[13px]">
				<dt class="text-muted">{t('denied.signedInAs')}</dt>
				<dd class="font-medium break-all">{session.denied.username}</dd>
				<dt class="text-muted">{t('denied.reason')}</dt>
				<dd class="font-medium">{t(reason === 'mfa' ? 'denied.reason.mfa' : 'denied.reason.group')}</dd>
			</dl>
		{/if}
		<div class="flex flex-wrap gap-2.5">
			<form method="POST" action="/auth/logout" class="flex flex-[1_1_160px]">
				<button type="submit" class="h-11 w-full rounded-[10px] bg-accent font-semibold text-[#18181b]"
					>{t('denied.signOut')}</button
				>
			</form>
			<form method="POST" action="/auth/logout?then=login" class="flex flex-[1_1_160px]">
				<button type="submit" class="h-11 w-full rounded-[10px] border border-line-strong font-medium"
					>{t('denied.another')}</button
				>
			</form>
		</div>
		<p class="text-[12.5px] text-muted">{t('denied.recorded')}</p>
	</main>
</div>
