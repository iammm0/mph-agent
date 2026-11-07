import { invoke } from "@tauri-apps/api/core";

export const CASE_LIBRARY_TARGET_VERSION = "COMSOL 6.3";

export interface CaseLibraryItem {
  id: string;
  applicationId: string;
  slug: string;
  title: string;
  category: string;
  summary: string;
  officialUrl: string;
  downloadUrl: string;
  referencePdfUrl: string;
  englishUrl: string;
  imageUrl: string;
  latestVersion: string;
  tags: string[];
  products: CaseLibraryProduct[];
  downloads: CaseLibraryDownload[];
}

export interface CaseLibraryProduct {
  name: string;
  url: string;
}

export interface CaseLibraryDownload {
  version: string;
  filename: string;
  url: string;
  size: string;
  fileType: string;
}

export interface CaseLibraryResult {
  items: CaseLibraryItem[];
  total: number;
  generatedAt: string | null;
  metadata: Record<string, unknown>;
  ok: boolean;
  message: string;
}

export interface CaseLibrarySyncState {
  running: boolean;
  status: string;
  message: string;
  savedItems: number;
  indexedItems: number;
  totalShallowRecords: number;
  detailCompleted?: number;
  detailTotal?: number;
  page?: number;
  title?: string;
  officialUrl?: string;
  startedAt?: string | null;
  finishedAt?: string | null;
  generatedAt?: string | null;
  lastError?: string | null;
  metadata: Record<string, unknown>;
}

interface CaseLibraryBridgeResponse {
  ok: boolean;
  message: string;
  items?: Array<Record<string, unknown>>;
  total?: number;
  generated_at?: string | null;
  metadata?: Record<string, unknown>;
  sync?: Record<string, unknown>;
}

interface FetchCaseLibraryOptions {
  limit?: number;
  query?: string;
  category?: string;
}

interface StartCaseLibrarySyncOptions {
  startPage?: number;
  endPage?: number;
  limit?: number;
  workers?: number;
  timeout?: number;
  delayMs?: number;
}

export function formatCaseLibraryTime(value: string | null | undefined): string {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;

  const parts = new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).formatToParts(date);

  const get = (type: Intl.DateTimeFormatPartTypes) =>
    parts.find((part) => part.type === type)?.value ?? "";

  return `${get("year")}-${get("month")}-${get("day")} ${get("hour")}:${get("minute")}:${get("second")}`;
}

function normalizeItem(raw: Record<string, unknown>): CaseLibraryItem | null {
  const id = typeof raw.id === "string" ? raw.id : "";
  const applicationId = typeof raw.application_id === "string" ? raw.application_id : id;
  const slug = typeof raw.slug === "string" ? raw.slug : "";
  const title = typeof raw.title === "string" ? raw.title : "";
  const category = typeof raw.category === "string" ? raw.category : "未分类";
  const summary = typeof raw.summary === "string" ? raw.summary : "";
  const officialUrl = typeof raw.official_url === "string" ? raw.official_url : "";
  const downloadUrl = typeof raw.download_url === "string" ? raw.download_url : "";
  const referencePdfUrl =
    typeof raw.reference_pdf_url === "string" ? raw.reference_pdf_url : "";
  const englishUrl = typeof raw.english_url === "string" ? raw.english_url : "";
  const imageUrl = typeof raw.image_url === "string" ? raw.image_url : "";
  const latestVersion = typeof raw.latest_version === "string" ? raw.latest_version : "";
  const tagsRaw = Array.isArray(raw.tags) ? raw.tags : [];
  const tags = tagsRaw.filter((tag): tag is string => typeof tag === "string");
  const productsRaw = Array.isArray(raw.products) ? raw.products : [];
  const products = productsRaw
    .filter((item): item is Record<string, unknown> => typeof item === "object" && item !== null)
    .map((item) => ({
      name: typeof item.name === "string" ? item.name : "",
      url: typeof item.url === "string" ? item.url : "",
    }))
    .filter((item) => item.name);
  const downloadsRaw = Array.isArray(raw.downloads) ? raw.downloads : [];
  const downloads = downloadsRaw
    .filter((item): item is Record<string, unknown> => typeof item === "object" && item !== null)
    .map((item) => ({
      version: typeof item.version === "string" ? item.version : "",
      filename: typeof item.filename === "string" ? item.filename : "",
      url: typeof item.url === "string" ? item.url : "",
      size: typeof item.size === "string" ? item.size : "",
      fileType: typeof item.file_type === "string" ? item.file_type : "",
    }))
    .filter((item) => item.url);
  if (!id || !title || !officialUrl || !downloadUrl) return null;
  return {
    id,
    applicationId,
    slug,
    title,
    category,
    summary,
    officialUrl,
    downloadUrl,
    referencePdfUrl,
    englishUrl,
    imageUrl,
    latestVersion,
    tags,
    products,
    downloads,
  };
}

function buildResult(
  items: CaseLibraryItem[],
  {
    total,
    generatedAt,
    metadata,
    ok,
    message,
  }: {
    total?: number;
    generatedAt?: string | null;
    metadata?: Record<string, unknown>;
    ok: boolean;
    message: string;
  }
): CaseLibraryResult {
  return {
    items,
    total: typeof total === "number" ? total : items.length,
    generatedAt: typeof generatedAt === "string" ? generatedAt : null,
    metadata: metadata ?? {},
    ok,
    message,
  };
}

function normalizeSync(raw: Record<string, unknown> | undefined | null): CaseLibrarySyncState | null {
  if (!raw) return null;
  return {
    running: raw.running === true,
    status: typeof raw.status === "string" ? raw.status : "idle",
    message: typeof raw.message === "string" ? raw.message : "",
    savedItems: typeof raw.saved_items === "number" ? raw.saved_items : 0,
    indexedItems: typeof raw.indexed_items === "number" ? raw.indexed_items : 0,
    totalShallowRecords:
      typeof raw.total_shallow_records === "number" ? raw.total_shallow_records : 0,
    detailCompleted:
      typeof raw.detail_completed === "number" ? raw.detail_completed : undefined,
    detailTotal: typeof raw.detail_total === "number" ? raw.detail_total : undefined,
    page: typeof raw.page === "number" ? raw.page : undefined,
    title: typeof raw.title === "string" ? raw.title : undefined,
    officialUrl: typeof raw.official_url === "string" ? raw.official_url : undefined,
    startedAt: typeof raw.started_at === "string" ? raw.started_at : null,
    finishedAt: typeof raw.finished_at === "string" ? raw.finished_at : null,
    generatedAt: typeof raw.generated_at === "string" ? raw.generated_at : null,
    lastError: typeof raw.last_error === "string" ? raw.last_error : null,
    metadata:
      raw.metadata && typeof raw.metadata === "object"
        ? (raw.metadata as Record<string, unknown>)
        : {},
  };
}

export async function fetchCaseLibrary(
  options: FetchCaseLibraryOptions = {}
): Promise<CaseLibraryResult> {
  const { limit = 200, query, category } = options;

  try {
    const res = await invoke<CaseLibraryBridgeResponse>("bridge_send", {
      cmd: "case_library_list",
      payload: { limit, query, category },
    });
    if (!res.ok || !Array.isArray(res.items)) {
      return buildResult([], {
        ok: false,
        message: res.message,
        total: typeof res.total === "number" ? res.total : 0,
        generatedAt: res.generated_at,
        metadata: res.metadata,
      });
    }
    const normalized = res.items
      .map((row) => normalizeItem(row))
      .filter((item): item is CaseLibraryItem => item != null);
    return buildResult(normalized, {
      total: typeof res.total === "number" ? res.total : normalized.length,
      generatedAt: res.generated_at,
      metadata: res.metadata,
      ok: true,
      message: res.message,
    });
  } catch (error) {
    return buildResult([], {
      ok: false,
      message: String(error),
      metadata: {},
    });
  }
}

export async function startCaseLibrarySync(
  options: StartCaseLibrarySyncOptions = {}
): Promise<CaseLibrarySyncState | null> {
  try {
    const res = await invoke<CaseLibraryBridgeResponse>("bridge_send", {
      cmd: "case_library_sync",
      payload: {
        start_page: options.startPage,
        end_page: options.endPage,
        limit: options.limit,
        workers: options.workers,
        timeout: options.timeout,
        delay_ms: options.delayMs,
      },
    });
    return normalizeSync(res.sync ?? null);
  } catch {
    return null;
  }
}

export async function fetchCaseLibrarySyncStatus(): Promise<CaseLibrarySyncState | null> {
  try {
    const res = await invoke<CaseLibraryBridgeResponse>("bridge_send", {
      cmd: "case_library_sync_status",
      payload: {},
    });
    return normalizeSync(res.sync ?? null);
  } catch {
    return null;
  }
}

export interface CaseLibraryDownloadRequestFile {
  url: string;
  filename?: string;
}

export interface CaseLibraryDownloadedFile {
  url: string;
  filename: string;
  path: string;
  size: number;
}

export interface CaseLibraryDownloadResult {
  ok: boolean;
  message: string;
  outputDir: string;
  files: CaseLibraryDownloadedFile[];
  errors: string[];
}

/** Prefer .mph, then .zip / archives, then other downloads. */
export function pickCaseDownloadFiles(item: CaseLibraryItem): CaseLibraryDownloadRequestFile[] {
  const fromList = item.downloads
    .filter((d) => d.url.trim())
    .map((d) => ({
      url: d.url.trim(),
      filename: d.filename.trim() || undefined,
    }));
  const ranked = [...fromList].sort((a, b) => {
    const score = (name: string, url: string) => {
      const text = `${name} ${url}`.toLowerCase();
      if (text.includes(".mph")) return 0;
      if (text.includes(".zip") || text.includes(".mphbin")) return 1;
      if (text.includes(".pdf")) return 3;
      return 2;
    };
    return score(a.filename || "", a.url) - score(b.filename || "", b.url);
  });
  const mphOrZip = ranked.filter((d) => {
    const text = `${d.filename || ""} ${d.url}`.toLowerCase();
    return text.includes(".mph") || text.includes(".zip") || text.includes(".mphbin");
  });
  if (mphOrZip.length > 0) return mphOrZip;
  if (ranked.length > 0) return ranked.slice(0, 1);
  if (item.downloadUrl.trim()) {
    return [{ url: item.downloadUrl.trim() }];
  }
  return [];
}

export async function downloadCaseLibraryFiles(options: {
  outputDir: string;
  files: CaseLibraryDownloadRequestFile[];
}): Promise<CaseLibraryDownloadResult> {
  try {
    const res = await invoke<{
      ok: boolean;
      message: string;
      output_dir?: string;
      files?: Array<Record<string, unknown>>;
      errors?: string[];
    }>("bridge_send", {
      cmd: "case_library_download",
      payload: {
        output_dir: options.outputDir,
        files: options.files,
      },
    });
    const files = Array.isArray(res.files)
      ? res.files
          .map((row) => ({
            url: typeof row.url === "string" ? row.url : "",
            filename: typeof row.filename === "string" ? row.filename : "",
            path: typeof row.path === "string" ? row.path : "",
            size: typeof row.size === "number" ? row.size : 0,
          }))
          .filter((row) => row.path)
      : [];
    return {
      ok: res.ok,
      message: res.message || "",
      outputDir: typeof res.output_dir === "string" ? res.output_dir : options.outputDir,
      files,
      errors: Array.isArray(res.errors)
        ? res.errors.filter((item): item is string => typeof item === "string")
        : [],
    };
  } catch (error) {
    return {
      ok: false,
      message: String(error),
      outputDir: options.outputDir,
      files: [],
      errors: [String(error)],
    };
  }
}
