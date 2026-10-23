// Fails when locale files do not share exactly the same keys and placeholders.
import { readdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';

const dir = join(import.meta.dirname, '..', 'src', 'lib', 'i18n');
const files = readdirSync(dir).filter((f) => f.endsWith('.json'));
const load = (f) => JSON.parse(readFileSync(join(dir, f), 'utf8'));
const base = load('en-US.json');
const vars = (s) =>
	[...s.matchAll(/\{(\w+)\}/g)]
		.map((m) => m[1])
		.sort()
		.join(',');
let failed = false;
for (const file of files) {
	const dict = load(file);
	for (const key of Object.keys(base)) {
		if (!(key in dict)) {
			console.error(`${file}: missing key ${key}`);
			failed = true;
		} else if (vars(dict[key]) !== vars(base[key])) {
			console.error(`${file}: placeholders differ for ${key}`);
			failed = true;
		}
	}
	for (const key of Object.keys(dict)) {
		if (!(key in base)) {
			console.error(`${file}: extra key ${key}`);
			failed = true;
		}
	}
}
if (failed) process.exit(1);
console.log(`locales OK (${files.join(', ')})`);
