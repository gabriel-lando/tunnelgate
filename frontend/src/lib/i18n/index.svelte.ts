import enUS from './en-US.json';
import ptBR from './pt-BR.json';

export type Dictionary = Record<string, string>;
export type MessageKey = keyof typeof enUS;

/** Add a language by dropping a JSON file here and registering it below. */
export const dictionaries: Record<string, Dictionary> = {
	'en-US': enUS,
	'pt-BR': ptBR
};

export const languageNames: Record<string, string> = {
	'en-US': 'English (US)',
	'pt-BR': 'Português (Brasil)'
};

export const FALLBACK = 'en-US';

export function detectLanguage(preferred: readonly string[]): string {
	for (const tag of preferred) {
		if (dictionaries[tag]) return tag;
		const base = tag.split('-')[0]?.toLowerCase();
		const match = Object.keys(dictionaries).find((k) => k.split('-')[0]?.toLowerCase() === base);
		if (match) return match;
	}
	return FALLBACK;
}

export function format(template: string, params: Record<string, string | number> = {}): string {
	return template.replace(/\{(\w+)\}/g, (whole, name: string) => (name in params ? String(params[name]) : whole));
}

class I18n {
	lang = $state(FALLBACK);

	t = (key: MessageKey, params?: Record<string, string | number>): string => {
		const dict = dictionaries[this.lang] ?? {};
		const template = dict[key] ?? (dictionaries[FALLBACK] as Dictionary)[key] ?? key;
		return format(template, params);
	};

	apply(preference: string): void {
		const nav = typeof navigator === 'undefined' ? [] : (navigator.languages ?? [navigator.language]);
		this.lang = preference !== 'auto' && dictionaries[preference] ? preference : detectLanguage(nav);
		if (typeof document !== 'undefined') document.documentElement.lang = this.lang;
	}
}

export const i18n = new I18n();
export const t = i18n.t;
