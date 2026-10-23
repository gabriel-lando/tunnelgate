<script lang="ts">
	import Icon from './Icon.svelte';
	import Modal from './Modal.svelte';
	import Toggle from './Toggle.svelte';
	import { t } from '#lib/i18n/index.svelte.ts';
	import { settings } from '#lib/settings.svelte.ts';
	import type { CloneRequest, OriginValue, Route, Tunnel, Zone } from '#lib/types.ts';
	import { isValidService, isValidSubdomain, subdomainOf } from '#lib/validation.ts';

	let {
		open,
		tunnel,
		route,
		zones,
		busy,
		error = null,
		onsubmit,
		onclose
	}: {
		open: boolean;
		tunnel: Tunnel | null;
		route: Route | null;
		zones: Zone[];
		busy: boolean;
		error?: string | null;
		onsubmit: (body: CloneRequest) => void;
		onclose: () => void;
	} = $props();

	let subdomain = $state('');
	let zoneId = $state('');
	let service = $state('');
	let path = $state('');
	let createBlocked = $state(false);
	let advanced = $state(false);
	let noTlsVerify = $state(false);
	let hostHeader = $state('');
	let sni = $state('');
	let timeout = $state('');
	let touched = $state(false);

	$effect(() => {
		if (!open || !route) return;
		const origin = route.origin_request;
		subdomain = `${subdomainOf(route.hostname, route.zone)}-copy`;
		zoneId = zones.find((z) => z.name === route.zone)?.id ?? zones[0]?.id ?? '';
		service = route.service ?? '';
		path = route.path ?? '';
		createBlocked = settings.prefs.createBlocked;
		noTlsVerify = origin['noTLSVerify'] === true;
		hostHeader = typeof origin['httpHostHeader'] === 'string' ? origin['httpHostHeader'] : '';
		sni = typeof origin['originServerName'] === 'string' ? origin['originServerName'] : '';
		timeout = typeof origin['connectTimeout'] === 'number' ? String(origin['connectTimeout']) : '';
		advanced = false;
		touched = false;
	});

	const zoneName = $derived(zones.find((z) => z.id === zoneId)?.name ?? '');
	const fqdn = $derived(`${subdomain.trim().toLowerCase()}.${zoneName}`);
	const subOk = $derived(isValidSubdomain(subdomain));
	const serviceOk = $derived(isValidService(service));
	const timeoutOk = $derived(timeout === '' || (/^\d+$/.test(timeout) && +timeout >= 1 && +timeout <= 600));
	const valid = $derived(subOk && serviceOk && timeoutOk && !!zoneId);

	function submit(event: SubmitEvent) {
		event.preventDefault();
		touched = true;
		if (!valid || !route) return;
		const originRequest: Record<string, OriginValue> = {
			noTLSVerify: noTlsVerify ? true : null,
			httpHostHeader: hostHeader.trim() || null,
			originServerName: sni.trim() || null,
			connectTimeout: timeout ? Number(timeout) : null
		};
		onsubmit({
			source_hostname: route.hostname,
			source_path: route.path,
			subdomain: subdomain.trim().toLowerCase(),
			zone_id: zoneId,
			service: service.trim(),
			path: path.trim() || null,
			origin_request: originRequest,
			create_blocked: createBlocked
		});
	}

	const input =
		'h-10 w-full rounded-lg border border-line-strong bg-bg px-3 text-sm text-ink outline-none focus:border-accent';
</script>

<Modal {open} title={t('clone.title')} labelId="clone-title" {onclose}>
	{#if route && tunnel}
		<form id="clone-form" class="flex flex-col gap-5" onsubmit={submit} novalidate>
			<p class="-mt-2 text-[13px] text-muted">
				{t('clone.from', { host: route.hostname, tunnel: tunnel.name })}
			</p>

			<div class="flex flex-col gap-1.5">
				<label for="clone-sub" class="font-medium">{t('clone.hostname')}</label>
				<div class="flex h-10 overflow-hidden rounded-lg border border-line-strong bg-bg focus-within:border-accent">
					<input
						id="clone-sub"
						bind:value={subdomain}
						autocomplete="off"
						spellcheck="false"
						aria-invalid={touched && !subOk}
						class="min-w-0 flex-1 bg-transparent px-3 text-ink outline-none"
					/>
					<select
						aria-label={t('clone.zone')}
						bind:value={zoneId}
						class="border-l border-line bg-surface-2 px-2.5 text-ink outline-none"
					>
						{#each zones as zone (zone.id)}
							<option value={zone.id}>.{zone.name}</option>
						{/each}
					</select>
				</div>
				{#if touched && !subOk}
					<span class="text-[12.5px] text-danger-ink">{t('clone.invalidSubdomain')}</span>
				{/if}
			</div>

			<div class="flex flex-col gap-1.5">
				<label for="clone-svc" class="font-medium">{t('clone.service')}</label>
				<input
					id="clone-svc"
					bind:value={service}
					autocomplete="off"
					spellcheck="false"
					aria-invalid={touched && !serviceOk}
					class="{input} font-mono text-[13px]"
				/>
				<span class="text-[12.5px] {touched && !serviceOk ? 'text-danger-ink' : 'text-muted'}">
					{touched && !serviceOk ? t('clone.invalidService') : t('clone.serviceHelp')}
				</span>
			</div>

			<div class="flex items-center gap-3">
				<div class="flex-1">
					<div class="font-medium">{t('clone.createBlocked')}</div>
					<div class="text-[12.5px] text-muted">{t('clone.createBlockedHelp')}</div>
				</div>
				<Toggle
					checked={createBlocked}
					label={t('clone.createBlocked')}
					onchange={() => (createBlocked = !createBlocked)}
				/>
			</div>

			<div class="rounded-xl border border-line">
				<button
					type="button"
					aria-expanded={advanced}
					class="flex h-11 w-full items-center gap-2 px-3.5 font-medium"
					onclick={() => (advanced = !advanced)}
				>
					<span class="transition-transform {advanced ? 'rotate-90' : ''}"><Icon name="chevron" size={16} /></span>
					{t('clone.advanced')}
					<span class="ml-auto text-[12.5px] font-normal text-muted">{t('clone.copied')}</span>
				</button>
				{#if advanced}
					<div class="grid grid-cols-1 gap-3.5 px-3.5 pt-1 pb-4 sm:grid-cols-2">
						<label class="flex flex-col gap-1.5 text-[13px] font-medium">
							{t('clone.path')}
							<input bind:value={path} placeholder={t('clone.pathPlaceholder')} class="{input} h-9 font-mono" />
						</label>
						<label class="flex flex-col gap-1.5 text-[13px] font-medium">
							{t('clone.connectTimeout')}
							<input
								bind:value={timeout}
								inputmode="numeric"
								placeholder={t('clone.notSet')}
								aria-invalid={!timeoutOk}
								class="{input} h-9"
							/>
						</label>
						<label class="flex flex-col gap-1.5 text-[13px] font-medium">
							{t('clone.hostHeader')}
							<input bind:value={hostHeader} placeholder={t('clone.notSet')} class="{input} h-9" />
						</label>
						<label class="flex flex-col gap-1.5 text-[13px] font-medium">
							{t('clone.sni')}
							<input bind:value={sni} placeholder={t('clone.notSet')} class="{input} h-9" />
						</label>
						<label class="flex min-h-9 cursor-pointer items-center gap-2.5 sm:col-span-2">
							<input type="checkbox" bind:checked={noTlsVerify} class="size-[18px] accent-accent" />
							<span class="font-medium">{t('clone.noTlsVerify')}</span>
							<span class="font-mono text-xs text-muted">noTLSVerify</span>
						</label>
					</div>
				{/if}
			</div>

			<div class="flex gap-2.5 rounded-xl bg-surface-2 px-3.5 py-3 text-[13px] text-muted">
				<span class="mt-0.5 shrink-0"><Icon name="info" size={16} /></span>
				<span>{t('clone.summary', { tunnel: tunnel.name, host: fqdn })}</span>
			</div>
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
			form="clone-form"
			disabled={busy}
			class="h-10 rounded-lg bg-accent px-4 font-semibold text-[#18181b] disabled:opacity-50"
			>{t('clone.submit')}</button
		>
	{/snippet}
</Modal>
