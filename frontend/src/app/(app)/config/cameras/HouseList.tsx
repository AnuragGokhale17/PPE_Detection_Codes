"use client";

import { cameraStatus, type PlantNode } from "../_shared/types";

export interface HouseMatch {
  houseId: number;
  /** Cameras whose area matched the search (when the house name itself didn't) */
  areaMatches: number | null;
}

export function matchHouses(plants: PlantNode[], query: string): Map<number, HouseMatch> {
  const q = query.trim().toLowerCase();
  const result = new Map<number, HouseMatch>();
  for (const plant of plants) {
    for (const house of plant.production_houses) {
      if (!q || house.name.toLowerCase().includes(q) || plant.name.toLowerCase().includes(q)) {
        result.set(house.id, { houseId: house.id, areaMatches: null });
        continue;
      }
      const n = house.cameras.filter((c) => c.area.toLowerCase().includes(q)).length;
      if (n) result.set(house.id, { houseId: house.id, areaMatches: n });
    }
  }
  return result;
}

export function HouseList({
  plants,
  matches,
  selectedId,
  onSelect,
}: {
  plants: PlantNode[];
  matches: Map<number, HouseMatch>;
  selectedId: number | null;
  onSelect: (id: number) => void;
}) {
  const visiblePlants = plants
    .map((p) => ({ ...p, production_houses: p.production_houses.filter((h) => matches.has(h.id)) }))
    .filter((p) => p.production_houses.length);

  if (!visiblePlants.length) {
    return <p className="px-3 py-6 text-center text-sm text-ink-3">No production houses or areas match.</p>;
  }

  return (
    <nav aria-label="Production houses" className="grid gap-4">
      {visiblePlants.map((plant) => (
        <div key={plant.id}>
          <p className="eyebrow px-3 pb-1">{plant.name}</p>
          <ul className="grid gap-0.5">
            {plant.production_houses.map((house) => {
              const offline = house.cameras.filter((c) => cameraStatus(c) === "offline").length;
              const enabled = house.cameras.filter((c) => c.enabled).length;
              const match = matches.get(house.id);
              const active = house.id === selectedId;
              return (
                <li key={house.id}>
                  <button
                    type="button"
                    aria-current={active ? "true" : undefined}
                    onClick={() => onSelect(house.id)}
                    className={`flex w-full items-center justify-between gap-2 rounded-md px-3 py-2 text-left text-[13px] transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-200 ${
                      active ? "bg-accent-50 text-accent-700" : "text-ink-2 hover:bg-surface-3 hover:text-ink"
                    }`}
                  >
                    <span className="min-w-0">
                      <span className="block truncate font-medium">{house.name}</span>
                      <span className="tabular block text-[11px] text-ink-3">
                        {match?.areaMatches != null
                          ? `${match.areaMatches} matching area${match.areaMatches === 1 ? "" : "s"}`
                          : `${enabled} of ${house.cameras.length} camera${house.cameras.length === 1 ? "" : "s"} enabled`}
                      </span>
                    </span>
                    {offline > 0 && <span className="pill pill-critical tabular">{offline} offline</span>}
                  </button>
                </li>
              );
            })}
          </ul>
        </div>
      ))}
    </nav>
  );
}
