import { fetchMe, loginUrl } from './api';
import type { Denied, Me } from './types';

class Session {
	me = $state<Me | null>(null);
	denied = $state<Denied | null>(null);
	ready = $state(false);
	offline = $state(false);

	async init(path: string): Promise<'ok' | 'denied' | 'anonymous' | 'offline'> {
		try {
			const result = await fetchMe();
			this.offline = false;
			if (result.kind === 'ok') {
				this.me = result.me;
				return 'ok';
			}
			if (result.kind === 'denied') {
				this.denied = result.denied;
				return 'denied';
			}
			if (path !== '/signed-out') window.location.assign(loginUrl());
			return 'anonymous';
		} catch {
			this.offline = true;
			return 'offline';
		} finally {
			this.ready = true;
		}
	}
}

export const session = new Session();
