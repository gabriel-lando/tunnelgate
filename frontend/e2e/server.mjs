// Minimal static server for E2E: serves the SPA build with the 200.html fallback.
import { createServer } from 'node:http';
import { readFile, stat } from 'node:fs/promises';
import { extname, join, normalize } from 'node:path';

const root = join(import.meta.dirname, '..', 'build');
/** @type {Record<string, string>} */
const types = {
	'.html': 'text/html',
	'.js': 'text/javascript',
	'.css': 'text/css',
	'.json': 'application/json',
	'.svg': 'image/svg+xml',
	'.png': 'image/png',
	'.woff2': 'font/woff2',
	'.webmanifest': 'application/manifest+json',
	'.txt': 'text/plain'
};

createServer(async (req, res) => {
	const path = normalize(decodeURIComponent(new URL(req.url ?? '/', 'http://x').pathname)).replace(/^(\.\.[/\\])+/, '');
	let file = join(root, path);
	try {
		if (!file.startsWith(root) || !(await stat(file)).isFile()) throw new Error();
	} catch {
		file = join(root, '200.html');
	}
	res.writeHead(200, { 'content-type': types[extname(file)] ?? 'application/octet-stream' });
	res.end(await readFile(file));
}).listen(Number(process.env.PORT ?? 4173), '127.0.0.1');
