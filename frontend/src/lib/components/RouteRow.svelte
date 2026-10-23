<script lang="ts">
	import Icon from './Icon.svelte';
	import Toggle from './Toggle.svelte';
	import { t } from '#lib/i18n/index.svelte.ts';
	import { settings } from '#lib/settings.svelte.ts';
	import type { Route } from '#lib/types.ts';

	let {
		route,
		editable,
		busy,
		ontoggle,
		onclone,
		onremove
	}: {
		route: Route;
		editable: boolean;
		busy: boolean;
		ontoggle: () => void;
		onclone: () => void;
		onremove: () => void;
	} = $props();

	// The menu is a popover (top layer): the card's overflow cannot clip it, and the browser closes it on
	// outside click, Escape or when another menu opens.
	const menuId = $props.id();
	let menuOpen = $state(false);
	let menu = $state<HTMLDivElement>();
	let trigger = $state<HTMLButtonElement>();

	function placeMenu() {
		if (!menu || !trigger) return;
		const r = trigger.getBoundingClientRect();
		const below = r.bottom + 4 + menu.offsetHeight <= window.innerHeight;
		menu.style.top = `${below ? r.bottom + 4 : r.top - menu.offsetHeight - 4}px`;
		menu.style.left = `${Math.max(8, r.right - menu.offsetWidth)}px`;
	}

	function pick(action: () => void) {
		menu?.hidePopover();
		action();
	}

	function closeMenu() {
		if (menuOpen) menu?.hidePopover();
	}

	const badge = $derived.by(() => {
		if (route.blocked) return { text: t('route.badge.blocked'), cls: 'bg-danger-soft text-danger-ink' };
		if (route.critical) return { text: t('route.badge.critical'), cls: 'bg-warn-soft text-warn-ink' };
		if (route.wildcard) return { text: t('route.badge.wildcard'), cls: 'bg-surface-2 text-muted' };
		if (!route.managed) return { text: t('route.badge.dnsOnly'), cls: 'bg-surface-2 text-muted' };
		return null;
	});

	const destination = $derived(
		settings.prefs.hideDest ? t('route.hidden') : (route.service ?? t('route.unknownService'))
	);
	const disabledTip = $derived(route.block_disabled_reason ? t(`route.disabled.${route.block_disabled_reason}`) : '');
	const canEdit = $derived(editable && route.managed);
</script>

<!-- The menu is positioned once when it opens; close it instead of following the page. -->
<svelte:window onscroll={closeMenu} onresize={closeMenu} />

<div class="flex items-center gap-1 border-t border-line py-2.5 pr-2 pl-4 sm:gap-3 sm:py-3 sm:pr-5 sm:pl-5">
	<div class="min-w-0 flex-1">
		<div class="flex min-w-0 items-center gap-2">
			<span class="truncate text-[14.5px] font-medium sm:text-sm">{route.hostname}</span>
			{#if route.path}
				<span class="shrink-0 font-mono text-xs text-muted">{route.path}</span>
			{/if}
			{#if badge}
				<span class="shrink-0 rounded-full px-2 py-px text-[11px] font-semibold sm:text-[11.5px] {badge.cls}"
					>{badge.text}</span
				>
			{/if}
		</div>
		<div class="truncate font-mono text-xs text-muted sm:text-[12.5px]">→ {destination}</div>
	</div>

	{#if canEdit}
		<div class="hidden items-center sm:flex">
			<button
				type="button"
				class="flex size-8 items-center justify-center rounded-lg text-muted hover:bg-surface-2"
				aria-label={t('route.clone')}
				title={t('route.clone')}
				onclick={onclone}><Icon name="copy" size={16} /></button
			>
			<button
				type="button"
				class="flex size-8 items-center justify-center rounded-lg text-muted hover:bg-surface-2"
				aria-label={t('route.remove')}
				title={t('route.remove')}
				onclick={onremove}><Icon name="trash" size={16} /></button
			>
		</div>
	{/if}

	<Toggle
		checked={!route.blocked}
		label={t(route.blocked ? 'route.allow' : 'route.block', { host: route.hostname })}
		disabled={!route.can_block}
		title={disabledTip}
		{busy}
		large
		onchange={ontoggle}
	/>

	{#if canEdit}
		<div class="sm:hidden">
			<button
				bind:this={trigger}
				type="button"
				class="flex h-11 w-9 items-center justify-center rounded-lg text-muted"
				aria-label={t('route.more', { host: route.hostname })}
				aria-haspopup="menu"
				aria-expanded={menuOpen}
				popovertarget={menuId}><Icon name="more" /></button
			>
			<div
				bind:this={menu}
				id={menuId}
				popover="auto"
				role="menu"
				class="inset-auto m-0 w-44 overflow-hidden rounded-xl border border-line bg-surface p-0 text-ink shadow-xl"
				ontoggle={(e) => {
					menuOpen = e.newState === 'open';
					if (menuOpen) placeMenu();
				}}
			>
				<button
					type="button"
					role="menuitem"
					class="flex h-11 w-full items-center gap-2 px-3 text-left hover:bg-surface-2"
					onclick={() => pick(onclone)}><Icon name="copy" size={16} />{t('route.clone')}</button
				>
				<button
					type="button"
					role="menuitem"
					class="flex h-11 w-full items-center gap-2 px-3 text-left text-danger-ink hover:bg-surface-2"
					onclick={() => pick(onremove)}><Icon name="trash" size={16} />{t('route.remove')}</button
				>
			</div>
		</div>
	{/if}
</div>
