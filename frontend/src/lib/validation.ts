const LABEL = '(?!-)[a-z0-9-]{1,63}(?<!-)';
const SUBDOMAIN_RE = new RegExp(`^(?:${LABEL}\\.)*${LABEL}$`);
const SERVICE_SCHEMES = new Set(['http:', 'https:', 'tcp:', 'ssh:', 'rdp:']);

export function isValidSubdomain(value: string): boolean {
	const v = value.trim().toLowerCase();
	return v.length > 0 && v.length <= 200 && SUBDOMAIN_RE.test(v);
}

export function isValidService(value: string): boolean {
	const v = value.trim();
	if (!v || v.length > 2048 || /\s/.test(v)) return false;
	try {
		const url = new URL(v);
		return SERVICE_SCHEMES.has(url.protocol) && !!url.hostname && !url.username && !url.password;
	} catch {
		return false;
	}
}

export function subdomainOf(hostname: string, zone: string | null): string {
	if (!zone || !hostname.endsWith(`.${zone}`)) return hostname.split('.')[0] ?? '';
	return hostname.slice(0, -(zone.length + 1));
}
