export interface Toast {
	id: number;
	message: string;
	kind: 'ok' | 'error';
}

class Toasts {
	items = $state<Toast[]>([]);
	private next = 1;

	push(message: string, kind: Toast['kind'] = 'ok'): void {
		const id = this.next++;
		this.items = [...this.items, { id, message, kind }];
		setTimeout(() => this.dismiss(id), kind === 'error' ? 8000 : 4000);
	}

	dismiss(id: number): void {
		this.items = this.items.filter((t) => t.id !== id);
	}
}

export const toasts = new Toasts();
