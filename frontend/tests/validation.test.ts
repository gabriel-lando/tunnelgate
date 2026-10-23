import { describe, expect, it } from 'vitest';
import { isValidService, isValidSubdomain, subdomainOf } from '../src/lib/validation.ts';

describe('validation', () => {
	it.each([
		['app', true],
		['a.b-c', true],
		['-bad', false],
		['bad_', false],
		['', false],
		['x'.repeat(64), false],
		['a b', false]
	])('subdomain %s -> %s', (value, ok) => {
		expect(isValidSubdomain(value)).toBe(ok);
	});

	it.each([
		['http://gitea:3000', true],
		['https://10.0.0.5:8443/path', true],
		['ssh://host:22', true],
		['http_status:404', false],
		['javascript:alert(1)', false],
		['http://user:pw@host', false],
		['ftp://host', false],
		['http://host name', false]
	])('service %s -> %s', (value, ok) => {
		expect(isValidService(value)).toBe(ok);
	});

	it('extracts the subdomain relative to the zone', () => {
		expect(subdomainOf('vault.example.com', 'example.com')).toBe('vault');
		expect(subdomainOf('a.b.example.com', 'example.com')).toBe('a.b');
		expect(subdomainOf('vault.other.org', 'example.com')).toBe('vault');
	});
});
