import { apiGet, apiPost, query } from "./client";
import type {
  DemandPoint,
  ForecastResponse,
  InventoryRow,
  Region,
  Sku,
  Supplier,
  SupplierDetail,
  SupplierSearchRequest,
  SupplierSearchResult,
} from "./types";

export const listRegions = (signal?: AbortSignal) => apiGet<Region[]>("/api/regions", signal);

export const listSkus = (signal?: AbortSignal) => apiGet<Sku[]>("/api/skus", signal);

export const getDemand = (skuId: string, weeks = 52, signal?: AbortSignal) =>
  apiGet<DemandPoint[]>(`/api/demand${query({ skuId, weeks })}`, signal);

export const getInventory = (skuId: string, signal?: AbortSignal) =>
  apiGet<InventoryRow[]>(`/api/inventory${query({ skuId })}`, signal);

export const listSuppliers = (
  filters: { regionId?: string; certification?: string; minReliability?: number } = {},
  signal?: AbortSignal,
) => apiGet<Supplier[]>(`/api/suppliers${query(filters)}`, signal);

export const getSupplier = (supplierId: string, signal?: AbortSignal) =>
  apiGet<SupplierDetail>(`/api/suppliers/${encodeURIComponent(supplierId)}`, signal);

export const searchSuppliers = (request: SupplierSearchRequest) =>
  apiPost<SupplierSearchResult>("/api/suppliers/search", request);

export const getForecast = (
  skuId: string,
  regionId: string,
  asOf: string,
  horizonWeeks: number,
) => apiPost<ForecastResponse>("/api/forecasts", { skuId, regionId, asOf, horizonWeeks });

export function nextWeekStart(lastObservedWeek: string): string {
  const date = new Date(`${lastObservedWeek}T00:00:00Z`);
  date.setUTCDate(date.getUTCDate() + 7);
  return date.toISOString().slice(0, 10);
}
