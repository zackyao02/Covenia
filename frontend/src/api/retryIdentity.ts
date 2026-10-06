/** Keeps a mutation's idempotency identity stable while the operator retries it. */
export class RetryIdentityStore {
  private readonly entries = new Map<string, { fingerprint: string; idempotencyKey: string; eventId?: string }>();

  get(scope: string, payload: unknown, withEventId = false) {
    const fingerprint = JSON.stringify(payload);
    const current = this.entries.get(scope);
    if (current?.fingerprint === fingerprint) return current;

    const next = {
      fingerprint,
      idempotencyKey: `${scope}-${crypto.randomUUID()}`,
      ...(withEventId ? { eventId: `EVT_${crypto.randomUUID()}` } : {}),
    };
    this.entries.set(scope, next);
    return next;
  }

  clear(scope: string) {
    this.entries.delete(scope);
  }
}
