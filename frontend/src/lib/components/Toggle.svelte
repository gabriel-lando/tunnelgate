<script lang="ts">
	let {
		checked,
		label,
		disabled = false,
		busy = false,
		title = '',
		large = false,
		onchange
	}: {
		checked: boolean;
		label: string;
		disabled?: boolean;
		busy?: boolean;
		title?: string;
		large?: boolean;
		onchange: () => void;
	} = $props();
</script>

<button
	type="button"
	role="switch"
	aria-checked={checked}
	aria-label={label}
	aria-busy={busy}
	{title}
	disabled={disabled || busy}
	onclick={onchange}
	class="flex shrink-0 items-center justify-center disabled:cursor-not-allowed {large
		? 'h-11 w-13'
		: 'h-8 w-11'} {disabled ? 'opacity-45' : ''}"
>
	<span
		class="flex rounded-full p-0.5 transition-colors {large ? 'h-[26px] w-11' : 'h-6 w-11'} {checked
			? 'justify-end bg-accent'
			: 'justify-start bg-track-off'} {busy ? 'animate-pulse' : ''}"
	>
		<span class="rounded-full bg-white shadow {large ? 'size-[22px]' : 'size-5'}"></span>
	</span>
</button>
