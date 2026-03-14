import { invoke } from "@tauri-apps/api/core";
import type { BridgeResponse } from "./types";

export interface ApiWrapperItem {
  wrapper_name: string;
  owner: string;
  method_name: string;
}

export interface ListApisResponse extends BridgeResponse {
  apis?: ApiWrapperItem[];
  total?: number;
  limit?: number;
  offset?: number;
}

export async function listOfficialApis(params: {
  query?: string;
  limit?: number;
  offset?: number;
}): Promise<ListApisResponse> {
  const payload: Record<string, unknown> = {};
  if (params.query) payload.query = params.query;
  if (typeof params.limit === "number") payload.limit = params.limit;
  if (typeof params.offset === "number") payload.offset = params.offset;
  const res = await invoke<ListApisResponse>("bridge_send", {
    cmd: "list_apis",
    payload,
  });
  return res;
}

