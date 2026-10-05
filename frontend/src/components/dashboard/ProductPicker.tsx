"use client";

import { useState } from "react";
import type { Sku } from "@/lib/api/types";
import { humanize } from "@/lib/format";

const ALL = "ALL";

export function filterProducts(skus: Sku[], category: string, search: string): Sku[] {
  const text = search.trim().toLowerCase();
  return skus.filter(
    (s) =>
      (category === ALL || s.category === category) &&
      (!text || [s.name, s.skuId, s.category].some((field) => field.toLowerCase().includes(text))),
  );
}

export function ProductPicker({
  skus,
  selected,
  onSelect,
}: {
  skus: Sku[];
  selected: Sku;
  onSelect: (skuId: string) => void;
}) {
  const [category, setCategory] = useState(ALL);
  const [search, setSearch] = useState("");
  const categories = [...new Set(skus.map((s) => s.category))].sort();
  const visible = filterProducts(skus, category, search);

  // Narrowing the list moves the choice to the first match, so the page always shows what the list shows.
  function narrow(nextCategory: string, nextSearch: string) {
    setCategory(nextCategory);
    setSearch(nextSearch);
    const matches = filterProducts(skus, nextCategory, nextSearch);
    if (matches.length > 0 && !matches.some((s) => s.skuId === selected.skuId)) onSelect(matches[0].skuId);
  }

  return (
    <div className="stack product-picker">
      <div className="picker">
        <span className="picker-label" id="category-label">
          Category
        </span>
        <div className="segmented" role="group" aria-labelledby="category-label">
          {[ALL, ...categories].map((c) => (
            <button key={c} type="button" aria-pressed={c === category} onClick={() => narrow(c, search)}>
              {c === ALL ? "All" : humanize(c)}
            </button>
          ))}
        </div>
      </div>
      <div className="picker">
        <label className="field picker-search">
          <span>Search</span>
          <input
            type="search"
            value={search}
            placeholder="e.g. earbuds"
            onChange={(e) => narrow(category, e.target.value)}
          />
        </label>
        <label className="field picker-select">
          <span>Product</span>
          <select
            value={visible.some((s) => s.skuId === selected.skuId) ? selected.skuId : ""}
            onChange={(e) => onSelect(e.target.value)}
            disabled={visible.length === 0}
          >
            {visible.length === 0 ? <option value="">No match</option> : null}
            {visible.map((s) => (
              <option key={s.skuId} value={s.skuId}>
                {s.name}
              </option>
            ))}
          </select>
        </label>
        <ul className="facts" aria-label="About this product">
          <li>Code {selected.skuId}</li>
          <li>{humanize(selected.category)}</li>
          <li>${selected.unitPrice.toFixed(2)} each</li>
          {selected.requiredCertifications.length > 0 ? (
            <li>Needs {selected.requiredCertifications.join(", ")}</li>
          ) : null}
        </ul>
      </div>
      {visible.length === 0 ? (
        <p className="muted">No product matches “{search.trim()}”. Still showing {selected.name}.</p>
      ) : (
        <p className="muted small">
          {visible.length} of {skus.length} products
        </p>
      )}
    </div>
  );
}
