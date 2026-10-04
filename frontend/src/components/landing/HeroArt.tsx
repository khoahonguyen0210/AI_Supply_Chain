
import type { JSX } from "react";

export type ArtKind = "forecast" | "suppliers" | "plan" | "assistant";

function Forecast() {
  return (
    <>
      <polygon className="art-soft" points="300,150 340,128 380,140 420,104 460,112 460,206 420,196 380,214 340,196 300,186" />
      <polyline
        className="art-ink art-draw"
        points="20,230 60,214 100,236 140,196 180,208 220,170 260,186 300,168"
      />
      <polyline className="art-light art-dash" points="300,168 340,160 380,176 420,150 460,158" />
      <line className="art-axis" x1="20" y1="290" x2="460" y2="290" />
      <line className="art-split" x1="300" y1="60" x2="300" y2="290" />
      <text className="art-label" x="20" y="54">
        Sold
      </text>
      <text className="art-label art-label-light" x="312" y="54">
        Forecast
      </text>
    </>
  );
}

const SUPPLIER_BARS = [
  { name: "Supplier A", width: 300, chosen: false },
  { name: "Supplier B", width: 228, chosen: true },
  { name: "Supplier C", width: 340, chosen: false },
  { name: "Supplier D", width: 262, chosen: false },
];

function Suppliers() {
  return (
    <>
      {SUPPLIER_BARS.map((bar, i) => (
        <g key={bar.name}>
          <text className={bar.chosen ? "art-label art-label-light" : "art-label"} x="20" y={66 + i * 64}>
            {bar.name}
          </text>
          <rect
            className={bar.chosen ? "art-fill-light art-grow" : "art-fill art-grow"}
            x="130"
            y={44 + i * 64}
            width={bar.width}
            height="30"
            style={{ animationDelay: `${i * 90}ms` }}
          />
        </g>
      ))}
      <line className="art-axis" x1="130" y1="30" x2="130" y2="290" />
    </>
  );
}

function Plan() {
  const sources = [70, 160, 250];
  const targets = [110, 210];
  return (
    <>
      {sources.flatMap((sy) =>
        targets.map((ty) => <line key={`${sy}-${ty}`} className="art-link" x1="96" y1={sy} x2="384" y2={ty} />),
      )}
      {sources.map((sy) => (
        <rect key={sy} className="art-fill" x="40" y={sy - 28} width="56" height="56" />
      ))}
      {targets.map((ty) => (
        <rect key={ty} className="art-fill-light" x="384" y={ty - 36} width="72" height="72" />
      ))}
      <text className="art-label" x="40" y="300">
        Suppliers
      </text>
      <text className="art-label art-label-light" x="456" y="300" textAnchor="end">
        Warehouses
      </text>
    </>
  );
}

function Assistant() {
  return (
    <>
      <rect className="art-fill-light" x="150" y="30" width="310" height="86" />
      <rect className="art-text-ink" x="174" y="56" width="230" height="10" />
      <rect className="art-text-ink" x="174" y="80" width="160" height="10" />
      <rect className="art-fill" x="20" y="140" width="340" height="140" />
      <rect className="art-text-light" x="44" y="166" width="280" height="10" />
      <rect className="art-text-light" x="44" y="190" width="250" height="10" />
      <rect className="art-text-light" x="44" y="214" width="200" height="10" />
      <rect className="art-chip" x="44" y="242" width="76" height="20" />
      <rect className="art-chip" x="130" y="242" width="76" height="20" />
    </>
  );
}

const ART: Record<ArtKind, () => JSX.Element> = {
  forecast: Forecast,
  suppliers: Suppliers,
  plan: Plan,
  assistant: Assistant,
};

export function HeroArt({ kind }: { kind: ArtKind }) {
  const Drawing = ART[kind];
  return (
    <svg className="hero-art-svg" viewBox="0 0 480 320" aria-hidden="true" focusable="false">
      <Drawing />
    </svg>
  );
}
