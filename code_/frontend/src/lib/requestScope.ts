/** Tracks which request may update the currently displayed conversation. */
export class RequestScope {
  active: AbortController | null = null;

  begin(): AbortController {
    this.cancel();
    this.active = new AbortController();
    return this.active;
  }

  owns(controller: AbortController): boolean {
    return this.active === controller;
  }

  finish(controller: AbortController): boolean {
    if (!this.owns(controller)) return false;
    this.active = null;
    return true;
  }

  cancel(): void {
    this.active?.abort();
    this.active = null;
  }
}
