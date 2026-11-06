/* A document revision is acknowledged only after its persistence succeeds. */
class DocumentSession {
  constructor() { this.reset(); }
  reset(meta = {}) {
    this.id = meta.documentId || (globalThis.crypto && crypto.randomUUID ? crypto.randomUUID() : 'local-' + Math.random().toString(36).slice(2));
    this.revision = Number.isInteger(meta.revision) ? meta.revision : 0;
    this.savedRevision = meta.draftRecovered ? -1 : this.revision;
    this.ackRevision = meta.draftRecovered ? this.revision : -1;
    this.epoch = (this.epoch || 0) + 1;
  }
  edit() { this.revision += 1; }
  snapshot(markdown) { return { id: this.id, epoch: this.epoch, revision: this.revision, markdown }; }
  isCurrent(snapshot) { return snapshot.id === this.id && snapshot.epoch === this.epoch; }
  saved(snapshot) {
    if (!this.isCurrent(snapshot)) return false;
    this.savedRevision = Math.max(this.savedRevision, snapshot.revision);
    return this.revision === snapshot.revision;
  }
}
window.DocumentSession = DocumentSession;
