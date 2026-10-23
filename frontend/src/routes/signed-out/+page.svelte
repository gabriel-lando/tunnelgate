<script lang="ts">
	import Logo from '#lib/components/Logo.svelte';
	import { t } from '#lib/i18n/index.svelte.ts';
</script>

<div class="flex min-h-dvh flex-col items-center justify-center gap-6 bg-bg px-4 py-12">
	<Logo />
	<main class="flex w-full max-w-[440px] flex-col gap-4 rounded-2xl border border-line bg-surface p-8">
		<h1 class="text-[22px] font-semibold tracking-tight">{t('signedOut.title')}</h1>
		<p class="text-muted">{t('signedOut.body')}</p>
		<form method="GET" action="/auth/login">
			<button
				type="submit"
				class="flex h-11 w-full items-center justify-center rounded-[10px] bg-accent font-semibold text-[#18181b]"
				>{t('signedOut.signIn')}</button
			>
		</form>
	</main>
</div>
