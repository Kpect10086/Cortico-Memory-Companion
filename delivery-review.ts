import {existsSync, mkdirSync, readFileSync, renameSync, writeFileSync} from 'node:fs';
import {dirname} from 'node:path';
import type {EventEnvelope} from 'cortico/core/types.ts';

/** Deduplicate reviews and bound concurrent requests; only completed reviews are readable. */
export class ReviewCache {
  private readonly ready = new Map<string, string>();
  private readonly pending = new Map<string, Promise<string>>();
  private readonly failed = new Set<string>();
  private readonly queue: Array<() => void> = [];
  private active = 0;
  constructor(private readonly review: (text: string) => Promise<string>, private readonly concurrency = 2) {
    if (!Number.isInteger(concurrency) || concurrency < 1 || concurrency > 4) throw Error('Invalid memory review concurrency');
  }
  peek(text: string): string | undefined { return this.ready.get(text); }
  hasFailed(text: string): boolean { return this.failed.has(text); }
  get(text: string): Promise<string> {
    const ready = this.ready.get(text);
    if (ready !== undefined) return Promise.resolve(ready);
    const pending = this.pending.get(text);
    if (pending) return pending;
    this.failed.delete(text);
    let run!: () => void;
    const work = new Promise<string>((resolve, reject) => {
      run = () => {
        this.active++;
        Promise.resolve().then(() => this.review(text)).then(safe => {
          while (this.ready.size >= 998) this.ready.delete(this.ready.keys().next().value!);
          this.ready.set(text, safe);
          this.ready.set(safe, safe);
          resolve(safe);
        }, error => {
          while (this.failed.size >= 998) this.failed.delete(this.failed.values().next().value!);
          this.failed.add(text);
          reject(error);
        }).finally(() => {
          this.pending.delete(text);
          this.active--;
          this.pump();
        });
      };
    });
    this.pending.set(text, work);
    this.queue.push(run);
    this.pump();
    return work;
  }
  private pump(): void {
    // Leave review capacity for live replies and speech instead of filling every slot.
    while (this.active < this.concurrency && this.queue.length) this.queue.shift()!();
  }
}

type EventRef = {run: string; cursor: number};
const refKey = (ref: EventRef) => `${ref.run}:${ref.cursor}`;

/** Persist source references, never unreviewed bodies, before background archival. */
export class EventReviewQueue {
  private readonly pending = new Map<string, EventRef>();
  private readonly active = new Map<string, Promise<void>>();
  private readonly failed = new Set<string>();
  private stopped = true;
  constructor(private readonly file: string, private readonly archive: (ref: EventRef) => Promise<void>,
              private readonly onError: (ref: EventRef, error: unknown) => void) {
    if (existsSync(file)) {
      const refs: unknown = JSON.parse(readFileSync(file, 'utf8'));
      if (!Array.isArray(refs) || refs.some(ref => !ref || typeof ref.run !== 'string'
        || !Number.isSafeInteger(ref.cursor) || ref.cursor < 1)) throw Error('Invalid pending memory event references');
      for (const ref of refs as EventRef[]) this.pending.set(refKey(ref), ref);
    }
  }
  enqueue(events: readonly EventEnvelope[]): void {
    for (const event of events) {
      const ref = {run: event.run ?? '', cursor: event.cursor};
      this.pending.set(refKey(ref), ref);
    }
    this.save();
    this.pump();
  }
  start(): void { this.stopped = false; this.retry(); }
  retry(): void { this.failed.clear(); this.pump(); }
  async stop(): Promise<void> {
    this.stopped = true;
    await Promise.all(this.active.values());
  }
  private save(): void {
    mkdirSync(dirname(this.file), {recursive: true});
    writeFileSync(this.file + '.tmp', JSON.stringify([...this.pending.values()]));
    renameSync(this.file + '.tmp', this.file);
  }
  private pump(): void {
    if (this.stopped) return;
    for (const [id, ref] of this.pending) {
      if (this.active.size >= 4) break;
      if (this.active.has(id) || this.failed.has(id)) continue;
      const work = Promise.resolve().then(() => this.archive(ref)).then(() => {
        this.pending.delete(id);
        this.save();
      }).catch(error => {
        this.failed.add(id);
        this.onError(ref, error);
      }).finally(() => {
        this.active.delete(id);
        this.pump();
      });
      this.active.set(id, work);
    }
  }
}
