import adapter from '@sveltejs/adapter-static';
import { sveltekit } from '@sveltejs/kit/vite';
import tailwindcss from '@tailwindcss/vite';
import { defineConfig } from 'vitest/config';

export default defineConfig({
	plugins: [
		tailwindcss(),
		sveltekit({
			adapter: adapter({ pages: 'build', assets: 'build', fallback: '200.html', strict: true })
		})
	],
	server: {
		proxy: {
			'/api': 'http://127.0.0.1:8000',
			'/auth': 'http://127.0.0.1:8000'
		}
	},
	build: { sourcemap: false },
	test: {
		environment: 'jsdom',
		include: ['tests/**/*.test.ts'],
		coverage: { provider: 'v8', include: ['src/lib/**/*.ts'], thresholds: { lines: 70 } }
	}
});
