import { useRef, useState } from "react";
import { useStationCatalog } from "../hooks/useStationCatalog";
import type { PublicStation } from "../lib/api";
import Icon from "./Icon";

type Props = {
  stationId: string | null;
  disabled: boolean;
  onChange: (stationId: string) => void;
};

function StationOptions({ stations, selected, nearby, disabled, onChoose }: {
  stations: PublicStation[];
  selected: string | null;
  nearby: boolean;
  disabled: boolean;
  onChoose: (id: string) => void;
}) {
  return <ul className="station-list">{stations.map(station => <li key={station.id}>
    <button type="button" className="station-option" aria-pressed={selected === station.id}
      disabled={disabled} onClick={() => onChoose(station.id)}>
      <span><strong>{station.name}</strong><small>{station.county ? `${station.county} County` : "Washington"}</small></span>
      <span className="station-distance">{nearby
        ? station.distance_km === null ? "Distance unavailable" : `≈ ${(station.distance_km / 1.609344).toFixed(1)} mi`
        : selected === station.id ? "Selected" : "Choose"}</span>
    </button>
  </li>)}</ul>;
}

export default function LocationPicker({ stationId, disabled, onChange }: Props) {
  const dialog = useRef<HTMLDialogElement>(null);
  const searchInput = useRef<HTMLInputElement>(null);
  const [query, setQuery] = useState("");
  const { catalog, busy, error, nearby, showAll, findNearby, cancel } = useStationCatalog();
  const selected = catalog?.stations.find(station => station.id === stationId);
  const search = query.trim().toLocaleLowerCase();
  const stations = catalog?.stations.filter(station => `${station.name} ${station.county}`.toLocaleLowerCase().includes(search)) ?? [];
  const counties = catalog?.counties.filter(county => `${county} County`.toLocaleLowerCase().includes(search)) ?? [];
  const label = selected ? `${selected.name} · ${selected.county} County`
    : stationId ? "Station selected. Browse stations to view or change it." : "Choose a station with Browse stations";

  function open() {
    dialog.current?.showModal();
    searchInput.current?.focus();
    if (!catalog) void showAll();
  }
  function choose(id: string) {
    onChange(id);
    dialog.current?.close();
  }

  return <section className="location-picker" aria-label="Weather location">
    <div className="location-summary">
      <span>{label}</span>
      <button type="button" className="text-button" disabled={disabled} onClick={open}>Browse stations</button>
    </div>
    <dialog className="station-dialog" ref={dialog} aria-labelledby="station-dialog-title" onClose={cancel}
      onClick={event => { if (event.target === event.currentTarget) dialog.current?.close(); }}>
      <div className="station-dialog-content">
        <div className="station-dialog-heading">
          <div><h2 id="station-dialog-title">Choose a weather station</h2><p>Search by name or county, or find stations near you.</p></div>
          <button className="icon-button" type="button" aria-label="Close stations" onClick={() => dialog.current?.close()}><Icon name="close" /></button>
        </div>
        <button className="nearby-button" type="button" disabled={busy || disabled} onClick={() => { setQuery(""); findNearby(); }}>
          {busy ? "Finding stations…" : "Use my location"}
        </button>
        <p className="station-location-note">With your permission, we use your location to sort nearby stations. It isn’t saved to your conversation.</p>
        <label className="station-search"><Icon name="search" />
          <input ref={searchInput} type="search" aria-label="Search stations" placeholder="Search stations or counties"
            value={query} maxLength={100} onChange={event => setQuery(event.target.value)} />
        </label>
        {error && <div className="station-error" role="status">{error} <button type="button" className="text-button" disabled={busy} onClick={() => void showAll()}>Reload stations</button></div>}
        <div className="station-results" aria-busy={busy}>
          {!catalog && !error && <p role="status">Loading stations…</p>}
          {catalog && <>
            <div className="station-results-heading">
              <h3>{nearby ? "Nearest available stations" : "Available stations"}</h3>
              {nearby && <button className="text-button" type="button" disabled={busy} onClick={() => void showAll()}>Sort by name</button>}
            </div>
            <p className="station-coverage">{catalog.stations.length} stations across {catalog.counties.length} counties. Readings vary by station and date.</p>
            {nearby && catalog.located_count === 0 && <p role="status">Station locations are unavailable, so we can’t sort by distance right now.</p>}
            {!stations.length && <p role="status">No stations match “{query}”. Try another name or county.</p>}
            <StationOptions stations={stations} selected={stationId} nearby={nearby} disabled={disabled || busy} onChoose={choose} />
            {!!counties.length && <div className="county-options"><h3>Browse by county</h3>
              {counties.map(county => <button className="text-button" type="button" key={county} disabled={disabled || busy}
                onClick={() => setQuery(county)}>{county} County</button>)}
            </div>}
          </>}
        </div>
        <div className="station-dialog-footer">Choose a station to ask a weather question.</div>
      </div>
    </dialog>
  </section>;
}
