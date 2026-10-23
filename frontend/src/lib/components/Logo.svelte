<script lang="ts">
	import Icon from './Icon.svelte';
	let { small = false }: { small?: boolean } = $props();
</script>

<span class="flex items-center gap-2.5">
	<span class="flex items-center justify-center rounded-lg bg-accent text-[#18181b] {small ? 'size-7' : 'size-8'}">
		<Icon name="shield" size={small ? 16 : 18} />
	</span>
	<span class="text-base font-semibold">Tunnelgate</span>
</span>
