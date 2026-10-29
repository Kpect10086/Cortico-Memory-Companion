export interface MemoryRow { id: string; scope: string; text: string; kind: string; importance: number; reason: string; source: string; createdAt: number; state: string; processed: number; metadata: string }
export interface SearchOptions {view?:'memories'|'sources';from?:string|null;to?:string|null;offset?:number;limit?:number;now?:number}
export interface SearchReceipt {query:string;view:string;scopes:string[];includesSharedCore:boolean;from:string|null;to:string|null;eligibleRecords:number;matchedRecords:number;returnedRecords:number;nextOffset:number|null;queryComplete:boolean;outputComplete:boolean;historyCompleteness:string;note:string}
export interface SearchReport {rows:Array<MemoryRow & {sourceMessageIds?:string[];memoryIds?:string[];linkedMemoryCount?:number;textTruncated?:boolean}>;receipt:SearchReceipt}
export const DEFAULTS: { maxChars: number; coreChars: number; recentChars: number; recallChars: number; recentDays: number; summaryIntervalMinutes: number; singleThreshold: number };
export const MEMORY_WEIGHT_GUIDE: string;
export const MEMORY_ATTRIBUTION_GUIDE: string;
export const MEMORY_SELECTION_GUIDE: string;
export function chars(text: string): number;
export function key(text: string): string;
export function eventScopes(event: { source: string; senderKey?: string; meta?: Record<string, unknown> }): string[];
export function isMemoryEvent(event: {origin?:string;source:string;type:string;text?:string}): boolean;
export function eventSpeaker(event: {source:string;senderKey?:string;meta?:Record<string,unknown>}): string;
export class MemoryStore {
  constructor(file: string);
  db: import('node:sqlite').DatabaseSync;
  put(row: { id?: string; scope: string; text: string; source: string; kind?: string; importance?: number; reason?: string; createdAt?: number; state?: string; processed?: number; metadata?: Record<string, unknown> }): string;
  get(id: string): MemoryRow | undefined;
  eventRecord(source: string): string | undefined;
  archiveEvent(event: {scope:string;text:string;source:string;createdAt:number;run:string}): string;
  compactPendingEvents(): {sources:number;segments:number};
  search(query: string, scopes: string[], limit?: number, now?:number): MemoryRow[];
  lookup(query:string,scopes:string[],options?:SearchOptions): SearchReport;
  evidence(id: string, offset?: number, scopes?: string[], now?: number): {rows: {id:string;scope:string;speaker:string;receivedAt:number;text:string}[];matched:number;sourceIds:string[];missing:number;fragments:boolean};
  audit(scopes: string[], now?: number): {scanned:number;total:number;truncated:boolean;duplicates:{ids:string[];scope:string;approximate:boolean}[];missingSources:{id:string;missingMessages:number;missingRecords:number}[];note:string};
  captureMessage(input: {source:string;scope:string;text:string;createdAt:number;run?:string;speaker?:string}): void;
  remember(row: { text: string; sourceId?: string; sourceIds?: string[]; sourceMessageIds?: string[]; occurredAt?: string|null; timeConfidence?:number|null; timezone?:string; category?:string; importance: number; reason: string; kind: string }, scopes: string[], threshold?:number): string;
  manual(input: {text:string;scope:string;sourceType:string;kind:string;importance:number;reason:string;occurredAt?:string|null;effectiveAt?:string|null;tags?:string[];threshold?:number}): string;
  batchReview(items:Array<{id:string;revision:string}>,state:string,reason:string,threshold?:number): {count:number};
  restructure(items:Array<{id:string;revision:string}>,parts:Array<Parameters<MemoryStore['manual']>[0]>,reason:string): {ids:string[]};
  rollback(id:string,revision:string,reason:string): {ok:boolean};
  exportAll(approvedOnly?:boolean): {md:string;jsonl:string;count:number};
  exportFile(format:'json'|'md'|'sqlite'|'training',approvedOnly?:boolean): Promise<{$binary:{mime:string;base64:string}}>;
  reviewTraining(id:string,revision:string,approved:boolean,reason:string): {approved:boolean};
  importAll(jsonl:string): {count:number};
  autoApprove(threshold?:number): string[];
  review(id: string, state: string, reason: string, revision?: string, threshold?:number,actor?:string): void;
  correct(id: string, text: string, importance: number, reason: string, revision: string, changes?:Record<string,unknown>): string;
  pendingEvents(limit?: number): MemoryRow[];
  pack(scopes: string[], query: string, options?: Partial<typeof DEFAULTS>, now?: number): { text: string; intro: string; entries: {id:string;text:string}[]; chars: number; records: number };
  stats(): { total: number; pendingSummary: number; oldestPendingAt: number | null; kinds: unknown[] };
  close(): void;
}
