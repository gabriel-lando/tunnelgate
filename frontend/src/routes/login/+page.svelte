<script lang="ts">
	import { resolve } from '$app/paths';
	import Logo from '#lib/components/Logo.svelte';
	import { login } from '#lib/api.ts';
	import { t } from '#lib/i18n/index.svelte.ts';

	let username = $state('');
	let password = $state('');
	let busy = $state(false);
	let error = $state('');

	const input =
		'h-11 w-full rounded-lg border border-line-strong bg-bg px-3 text-sm text-ink outline-none focus:border-accent';

	async function submit(event: SubmitEvent) {
		event.preventDefault();
		if (busy) return;
		busy = true;
		error = '';
		const result = await login(username, password);
		if (result.ok) {
			window.location.assign(resolve('/'));
			return;
		}
		password = '';
		error =
			result.reason === 'invalid'
				? t('login.invalid')
				: result.reason === 'throttled'
					? t('login.throttled', { seconds: result.retryAfter })
					: t('login.error');
		busy = false;
	}
</script>

<div class="flex min-h-dvh flex-col items-center justify-center gap-6 bg-bg px-4 py-12">
	<Logo />
	<main class="flex w-full max-w-[440px] flex-col gap-5 rounded-2xl border border-line bg-surface p-8">
		<h1 class="text-[22px] font-semibold tracking-tight">{t('login.title')}</h1>
		<form class="flex flex-col gap-4" onsubmit={submit}>
			<label class="flex flex-col gap-1.5 text-[13px] font-medium">
				{t('login.username')}
				<input
					bind:value={username}
					name="username"
					autocomplete="username"
					autocapitalize="none"
					spellcheck="false"
					required
					maxlength="128"
					class={input}
				/>
			</label>
			<label class="flex flex-col gap-1.5 text-[13px] font-medium">
				{t('login.password')}
				<input
					bind:value={password}
					name="password"
					type="password"
					autocomplete="current-password"
					required
					maxlength="1024"
					class={input}
				/>
			</label>
			{#if error}
				<p role="alert" class="rounded-lg bg-danger-soft px-3.5 py-2.5 text-[13px] text-danger-ink">{error}</p>
			{/if}
			<button
				type="submit"
				disabled={busy}
				class="flex h-11 w-full items-center justify-center rounded-[10px] bg-accent font-semibold text-[#18181b] disabled:opacity-60"
				>{t('login.submit')}</button
			>
		</form>
	</main>
</div>
