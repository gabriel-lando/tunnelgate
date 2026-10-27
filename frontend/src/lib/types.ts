export type TunnelStatus = 'healthy' | 'degraded' | 'down' | 'inactive' | 'unknown';
export type BlockDisabledReason = 'no_zone_access';
export type OriginValue = boolean | number | string | null;

export interface Route {
	hostname: string;
	service: string | null;
	path: string | null;
	zone: string | null;
	blocked: boolean;
	wildcard: boolean;
	critical: boolean;
	managed: boolean;
	can_block: boolean;
	block_disabled_reason: BlockDisabledReason | null;
	origin_request: Record<string, unknown>;
}

export interface Tunnel {
	id: string;
	name: string;
	status: TunnelStatus;
	connections: number;
	replicas: number;
	versions: string[];
	remote_managed: boolean;
	can_undo: boolean;
	routes: Route[];
}

export interface Zone {
	id: string;
	name: string;
}

export interface State {
	tunnels: Tunnel[];
	zones: Zone[];
	generated_at: number;
}

export type AuthMode = 'oidc' | 'password';

export interface Me {
	username: string;
	name: string;
	groups: string[];
	csrf_token: string;
	expires_at: number;
}

export interface Denied {
	error: 'forbidden';
	reason: 'group' | 'mfa';
	username: string;
}

export interface About {
	version: string;
	commit: string;
	cloudflare_ok: boolean;
	token_status: string | null;
	token_expires_on: string | null;
	zones: string[];
}

export interface OperationResult {
	ok: boolean;
	message: string;
	blocked: string[];
	skipped: string[];
	state?: State | null;
}

export interface CloneRequest {
	source_hostname: string;
	source_path: string | null;
	subdomain: string;
	zone_id: string;
	service: string;
	path: string | null;
	origin_request: Record<string, OriginValue>;
	create_blocked: boolean;
}
