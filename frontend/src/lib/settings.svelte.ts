import { i18n } from './i18n/index.svelte';

export type ThemePref = 'system' | 'dark' | 'light';
export type RouteOrder = 'ingress' | 'alpha';

export interface Preferences {
	theme: ThemePref;
	language: string;
	createBlocked: boolean;
	hideDest: boolean;
	order: RouteOrder;
}

const KEY = 'tunnelgate.prefs';
const THEME_KEY = 'tunnelgate.theme';

export const defaults: Preferences = {
	theme: 'system',
	language: 'auto',
	createBlocked: true,
	hideDest: false,
	order: 'ingress'
};

export function parsePreferences(raw: string | null): Preferences {
	if (!raw) return { ...defaults };
	try {
		const data = JSON.parse(raw) as Partial<Preferences>;
		return {
			theme: ['system', 'dark', 'light'].includes(String(data.theme)) ? (data.theme as ThemePref) : defaults.theme,
			language: typeof data.language === 'string' ? data.language : defaults.language,
			createBlocked: data.createBlocked !== false,
			hideDest: data.hideDest === true,
			order: data.order === 'alpha' ? 'alpha' : 'ingress'
		};
	} catch {
		return { ...defaults };
	}
}

function read(): Preferences {
	try {
		return parsePreferences(localStorage.getItem(KEY));
	} catch {
		return { ...defaults };
	}
}

function write(p: Preferences): void {
	try {
		localStorage.setItem(KEY, JSON.stringify(p));
		localStorage.setItem(THEME_KEY, p.theme);
	} catch {
		// Storage can be unavailable (private mode); preferences then last for the session only.
	}
}

let media: MediaQueryList | null = null;

export function applyTheme(theme: ThemePref): void {
	if (typeof window === 'undefined') return;
	media ??= window.matchMedia('(prefers-color-scheme: dark)');
	const dark = theme === 'dark' || (theme === 'system' && media.matches);
	document.documentElement.classList.toggle('dark', dark);
}

class Settings {
	prefs = $state<Preferences>({ ...defaults });

	init(): void {
		this.prefs = read();
		this.applyAll();
		media ??= window.matchMedia('(prefers-color-scheme: dark)');
		media.addEventListener('change', () => applyTheme(this.prefs.theme));
	}

	update(patch: Partial<Preferences>): void {
		this.prefs = { ...this.prefs, ...patch };
		write(this.prefs);
		this.applyAll();
	}

	private applyAll(): void {
		applyTheme(this.prefs.theme);
		i18n.apply(this.prefs.language);
	}
}

export const settings = new Settings();
