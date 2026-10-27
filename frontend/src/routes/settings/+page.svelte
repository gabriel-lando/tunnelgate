<script lang="ts">
	import { resolve } from '$app/paths';
	import { onMount } from 'svelte';
	import { api } from '#lib/api.ts';
	import Icon from '#lib/components/Icon.svelte';
	import Logo from '#lib/components/Logo.svelte';
	import Toggle from '#lib/components/Toggle.svelte';
	import { dictionaries, i18n, languageNames, t } from '#lib/i18n/index.svelte.ts';
	import { session } from '#lib/session.svelte.ts';
	import { settings, type ThemePref } from '#lib/settings.svelte.ts';
	import type { About } from '#lib/types.ts';

	let about = $state<About | null>(null);

	onMount(async () => {
		try {
			about = await api.about();
		} catch {
			about = null;
		}
	});

	const themes: ThemePref[] = ['system', 'dark', 'light'];
	const expires = $derived(
		session.me
			? new Intl.DateTimeFormat(i18n.lang, { dateStyle: 'short', timeStyle: 'short' }).format(
					new Date(session.me.expires_at * 1000)
				)
			: ''
	);
	const initials = $derived(
		(session.me?.name ?? '?')
			.split(/\s+/)
			.map((p: string) => p[0] ?? '')
			.join('')
			.slice(0, 2)
			.toUpperCase()
	);

	const card = 'rounded-xl border border-line bg-surface';
	const heading =
		'px-4 pt-3.5 pb-1 text-xs font-semibold tracking-wider text-muted uppercase sm:px-5 sm:pt-4 sm:text-[13px]';
	const row = 'flex flex-col gap-3 px-4 py-3.5 sm:flex-row sm:items-center sm:gap-4 sm:px-5';
	const select =
		'h-11 rounded-[10px] border border-line bg-bg px-3 text-[15px] text-ink outline-none sm:h-9 sm:rounded-lg sm:text-sm';
</script>

<div class="min-h-dvh bg-bg">
	<header class="sticky top-0 z-10 border-b border-line bg-surface">
		<div class="mx-auto flex h-14 max-w-[1200px] items-center gap-1 px-1 sm:h-16 sm:px-6">
			<a
				href={resolve('/')}
				class="flex size-11 items-center justify-center rounded-lg text-muted sm:hidden"
				aria-label={t('nav.back')}><Icon name="back" size={22} /></a
			>
			<h1 class="text-[17px] font-semibold sm:hidden">{t('settings.title')}</h1>
			<span class="hidden sm:block"><Logo /></span>
		</div>
	</header>

	<main class="mx-auto flex max-w-[720px] flex-col gap-4 px-4 py-4 pb-10 sm:gap-5 sm:px-6 sm:py-7">
		<div class="hidden sm:block">
			<a href={resolve('/')} class="inline-flex items-center gap-1.5 text-[13px] font-medium text-muted no-underline">
				<Icon name="back" size={14} />{t('nav.back')}
			</a>
			<h1 class="mt-1.5 text-2xl font-semibold tracking-tight">{t('settings.title')}</h1>
			<p class="mt-1 text-muted">{t('settings.subtitle')}</p>
		</div>

		<section class={card}>
			<h2 class={heading}>{t('settings.appearance')}</h2>
			<div class={row}>
				<div class="flex-1">
					<div class="font-medium">{t('settings.theme')}</div>
					<div class="text-[13px] text-muted">{t('settings.themeHelp')}</div>
				</div>
				<div
					role="radiogroup"
					aria-label={t('settings.theme')}
					class="flex gap-0.5 rounded-[10px] bg-surface-2 p-[3px]"
				>
					{#each themes as theme (theme)}
						<button
							type="button"
							role="radio"
							aria-checked={settings.prefs.theme === theme}
							class="h-10 flex-1 rounded-lg px-3.5 text-sm font-medium sm:h-8 sm:flex-none sm:text-[13px] {settings
								.prefs.theme === theme
								? 'bg-surface text-ink shadow'
								: 'text-muted'}"
							onclick={() => settings.update({ theme })}>{t(`settings.theme.${theme}`)}</button
						>
					{/each}
				</div>
			</div>
			<div class="{row} border-t border-line">
				<label for="lang" class="flex-1">
					<div class="font-medium">{t('settings.language')}</div>
					<div class="text-[13px] text-muted">{t('settings.languageHelp')}</div>
				</label>
				<select
					id="lang"
					class={select}
					value={settings.prefs.language}
					onchange={(e) => settings.update({ language: e.currentTarget.value })}
				>
					<option value="auto">{t('settings.language.auto')}</option>
					{#each Object.keys(dictionaries) as code (code)}
						<option value={code}>{languageNames[code] ?? code}</option>
					{/each}
				</select>
			</div>
		</section>

		<section class={card}>
			<h2 class={heading}>{t('settings.behavior')}</h2>
			<div class="flex items-center gap-3 border-b border-line py-3 pr-2 pl-4 sm:pr-5 sm:pl-5">
				<div class="flex-1">
					<div class="font-medium">{t('settings.createBlocked')}</div>
					<div class="text-[13px] text-muted">{t('settings.createBlockedHelp')}</div>
				</div>
				<Toggle
					checked={settings.prefs.createBlocked}
					label={t('settings.createBlocked')}
					large
					onchange={() => settings.update({ createBlocked: !settings.prefs.createBlocked })}
				/>
			</div>
			<div class="flex items-center gap-3 border-b border-line py-3 pr-2 pl-4 sm:pr-5 sm:pl-5">
				<div class="flex-1">
					<div class="font-medium">{t('settings.hideDest')}</div>
					<div class="text-[13px] text-muted">{t('settings.hideDestHelp')}</div>
				</div>
				<Toggle
					checked={settings.prefs.hideDest}
					label={t('settings.hideDest')}
					large
					onchange={() => settings.update({ hideDest: !settings.prefs.hideDest })}
				/>
			</div>
			<div class={row}>
				<label for="order" class="flex-1">
					<div class="font-medium">{t('settings.order')}</div>
					<div class="text-[13px] text-muted">{t('settings.orderHelp')}</div>
				</label>
				<select
					id="order"
					class={select}
					value={settings.prefs.order}
					onchange={(e) => settings.update({ order: e.currentTarget.value === 'alpha' ? 'alpha' : 'ingress' })}
				>
					<option value="ingress">{t('settings.order.ingress')}</option>
					<option value="alpha">{t('settings.order.alpha')}</option>
				</select>
			</div>
		</section>

		{#if session.me}
			<section class={card}>
				<h2 class={heading}>{t('settings.session')}</h2>
				<div class={row}>
					<div class="flex flex-1 items-center gap-3.5">
						<span
							aria-hidden="true"
							class="flex size-10 shrink-0 items-center justify-center rounded-full bg-surface-2 text-[13px] font-semibold"
							>{initials}</span
						>
						<div class="min-w-0">
							<div class="font-medium">{session.me.name}</div>
							<div class="text-[13px] text-muted">
								{session.me.username}{session.me.groups.length ? ` · ${session.me.groups.join(', ')}` : ''}<br />{t(
									'settings.expires',
									{ time: expires }
								)}
							</div>
						</div>
					</div>
					<form method="POST" action="/auth/logout">
						<button
							type="submit"
							class="h-11 w-full rounded-[10px] border border-line px-3.5 font-medium hover:bg-surface-2 sm:h-9 sm:w-auto sm:rounded-lg"
							>{t('settings.signOut')}</button
						>
					</form>
				</div>
			</section>
		{/if}

		<section class={card}>
			<h2 class={heading}>{t('settings.about')}</h2>
			<dl class="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2.5 px-4 pt-2 pb-4 sm:grid-cols-[180px_1fr] sm:px-5">
				<dt class="text-muted">{t('settings.version')}</dt>
				<dd class="font-mono text-[13px]">{about ? `${about.version} · ${about.commit.slice(0, 12)}` : '…'}</dd>
				<dt class="text-muted">{t('settings.cloudflare')}</dt>
				<dd class="flex items-center gap-2">
					<span class="size-2 rounded-full {about?.cloudflare_ok ? 'bg-ok' : 'bg-down'}"></span>
					{about?.cloudflare_ok
						? t('settings.connected', { status: about.token_status ?? '?' })
						: t('settings.disconnected')}
				</dd>
				<dt class="text-muted">{t('settings.zones')}</dt>
				<dd class="flex flex-wrap gap-1.5">
					{#each about?.zones ?? [] as zone (zone)}
						<span class="rounded-full bg-surface-2 px-2 py-0.5 text-[12.5px] font-medium">{zone}</span>
					{/each}
				</dd>
			</dl>
		</section>
	</main>
</div>
