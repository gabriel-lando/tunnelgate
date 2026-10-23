/// <reference types="@sveltejs/kit" />
import { self } from '$app/service-worker';
import { assets, immutable, prerendered } from '$app/manifest';
import { version } from '$app/env';

// Caches only the app shell. API and auth responses are never cached so the
// dashboard can never show stale tunnel or block state.
const CACHE = `tunnelgate-shell-${version}`;
const SHELL = [...immutable, ...assets, ...prerendered].map((f) => f.path);
const NEVER_CACHE = /^\/(api|auth|healthz)(\/|$)/;

self.addEventListener('install', (event) => {
	event.waitUntil(
		caches
			.open(CACHE)
			.then((cache) => cache.addAll(SHELL))
			.then(() => self.skipWaiting())
	);
});

self.addEventListener('activate', (event) => {
	event.waitUntil(
		caches
			.keys()
			.then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
			.then(() => self.clients.claim())
	);
});

self.addEventListener('fetch', (event) => {
	const req = event.request;
	const url = new URL(req.url);
	if (req.method !== 'GET' || url.origin !== self.location.origin || NEVER_CACHE.test(url.pathname)) return;

	event.respondWith(
		(async () => {
			const cache = await caches.open(CACHE);
			if (SHELL.includes(url.pathname) && !req.headers.has('range')) {
				const hit = await cache.match(url.pathname);
				if (hit && immutable.some((f) => f.path === url.pathname)) return hit;
			}
			try {
				return await fetch(req);
			} catch {
				const fallback =
					(await cache.match(url.pathname)) ?? (req.mode === 'navigate' ? await cache.match('/') : undefined);
				return fallback ?? Response.error();
			}
		})()
	);
});
