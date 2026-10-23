import { describe, expect, it } from 'vitest';
import { defaults, parsePreferences } from '../src/lib/settings.svelte.ts';

describe('preferences', () => {
	it('falls back to defaults on bad input', () => {
		expect(parsePreferences(null)).toEqual(defaults);
		expect(parsePreferences('{oops')).toEqual(defaults);
		expect(parsePreferences('{"theme":"neon","order":"random","hideDest":"yes"}')).toEqual(defaults);
		expect(defaults.createBlocked).toBe(true);
		expect(parsePreferences('{"createBlocked":false}').createBlocked).toBe(false);
	});

	it('keeps valid values', () => {
		const p = parsePreferences(
			'{"theme":"dark","language":"pt-BR","createBlocked":true,"hideDest":true,"order":"alpha"}'
		);
		expect(p).toEqual({ theme: 'dark', language: 'pt-BR', createBlocked: true, hideDest: true, order: 'alpha' });
	});
});
