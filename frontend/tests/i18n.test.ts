import { describe, expect, it } from 'vitest';
import enUS from '../src/lib/i18n/en-US.json';
import ptBR from '../src/lib/i18n/pt-BR.json';
import { detectLanguage, format, i18n } from '../src/lib/i18n/index.svelte.ts';

describe('i18n', () => {
	it('locales share the same keys', () => {
		expect(Object.keys(ptBR).sort()).toEqual(Object.keys(enUS).sort());
	});

	it('detects exact and base languages, falling back to en-US', () => {
		expect(detectLanguage(['pt-BR'])).toBe('pt-BR');
		expect(detectLanguage(['pt-PT'])).toBe('pt-BR');
		expect(detectLanguage(['de-DE', 'fr'])).toBe('en-US');
		expect(detectLanguage([])).toBe('en-US');
	});

	it('formats placeholders and keeps unknown ones', () => {
		expect(format('{a} and {b}', { a: 1 })).toBe('1 and {b}');
	});

	it('translates with an explicit preference', () => {
		i18n.apply('pt-BR');
		expect(i18n.t('dashboard.title')).toBe('Túneis');
		i18n.apply('en-US');
		expect(i18n.t('tunnel.replicas', { count: 4 })).toBe('4 replicas');
	});
});
