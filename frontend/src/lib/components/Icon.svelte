<script lang="ts" module>
	export const paths = {
		shield: ['M12 3l8 3v6c0 4.5-3.4 8.3-8 9-4.6-.7-8-4.5-8-9V6l8-3z', 'M9 12l2 2 4-4'],
		search: ['M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14z', 'M20 20l-3.5-3.5'],
		refresh: ['M21 12a9 9 0 1 1-2.64-6.36', 'M21 3v6h-6'],
		settings: [
			'M4 6h9M17 6h3M4 12h3M11 12h9M4 18h11M19 18h1',
			'M15 4a2 2 0 1 0 0 4 2 2 0 0 0 0-4zM9 10a2 2 0 1 0 0 4 2 2 0 0 0 0-4zM17 16a2 2 0 1 0 0 4 2 2 0 0 0 0-4z'
		],
		power: ['M12 3v9', 'M6.3 7.5a8 8 0 1 0 11.4 0'],
		copy: ['M11 9h7a2 2 0 0 1 2 2v7a2 2 0 0 1-2 2h-7a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2z', 'M5 15V6a2 2 0 0 1 2-2h9'],
		trash: ['M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3'],
		close: ['M6 6l12 12M18 6L6 18'],
		back: ['M15 18l-6-6 6-6'],
		chevron: ['M9 6l6 6-6 6'],
		info: ['M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18z', 'M12 11v5M12 8h.01'],
		lock: ['M7 11h10a2 2 0 0 1 2 2v6a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2v-6a2 2 0 0 1 2-2z', 'M8 11V7a4 4 0 0 1 8 0v4'],
		undo: ['M9 14L4 9l5-5', 'M4 9h11a5 5 0 0 1 0 10h-3'],
		more: ['M12 5h.01M12 12h.01M12 19h.01'],
		wifiOff: ['M2 2l20 20', 'M8.5 16.5a5 5 0 0 1 7 0', 'M5 12.9a10 10 0 0 1 5.2-2.7', 'M12 20h.01']
	} as const;
	export type IconName = keyof typeof paths;
</script>

<script lang="ts">
	let { name, size = 18, stroke = 2 }: { name: IconName; size?: number; stroke?: number } = $props();
	const isDots = $derived(name === 'more');
</script>

<svg
	width={size}
	height={size}
	viewBox="0 0 24 24"
	fill="none"
	stroke="currentColor"
	stroke-width={isDots ? 3.5 : stroke}
	stroke-linecap="round"
	stroke-linejoin="round"
	aria-hidden="true"
>
	{#each paths[name] as d (d)}
		<path {d} />
	{/each}
</svg>
