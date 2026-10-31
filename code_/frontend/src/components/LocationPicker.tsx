import { useEffect, useRef, useState } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import type { RequestedPoint } from "../lib/api";

type Props = {
  point: RequestedPoint | null;
  disabled: boolean;
  onChange: (point: RequestedPoint) => void;
};

export default function LocationPicker({ point, disabled, onChange }: Props) {
  const container = useRef<HTMLDivElement>(null);
  const map = useRef<L.Map | null>(null);
  const marker = useRef<L.CircleMarker | null>(null);
  const action = useRef({ disabled, onChange });
  const [tileError, setTileError] = useState(false);

  useEffect(() => {
    action.current = { disabled, onChange };
  }, [disabled, onChange]);

  useEffect(() => {
    if (!container.current) return;
    const view = L.map(container.current).setView([47.2, -120.5], 6);
    map.current = view;
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
      maxZoom: 18,
    })
      .on("tileerror", () => setTileError(true))
      .addTo(view);
    view.on("click", (event: L.LeafletMouseEvent) => {
      if (!action.current.disabled) {
        action.current.onChange({ latitude: event.latlng.lat, longitude: event.latlng.wrap().lng });
      }
    });
    const resize = new ResizeObserver(() => view.invalidateSize());
    resize.observe(container.current);
    return () => {
      resize.disconnect();
      view.remove();
      map.current = null;
      marker.current = null;
    };
  }, []);

  useEffect(() => {
    const view = map.current;
    if (!view) return;
    marker.current?.remove();
    if (point && !view.getBounds().contains([point.latitude, point.longitude]))
      view.panTo([point.latitude, point.longitude]);
    marker.current = point
      ? L.circleMarker([point.latitude, point.longitude], {
          radius: 8,
          color: "#981e32",
          fillOpacity: 0.8,
        }).addTo(view)
      : null;
  }, [point]);

  function chooseCenter() {
    const center = map.current?.getCenter().wrap();
    if (center && !disabled) onChange({ latitude: center.lat, longitude: center.lng });
  }

  return (
    <section className="location-picker" aria-label="Weather location">
      <p id="map-help">Choose a point on the map. Measurements come from a nearby weather source.</p>
      <div
        ref={container}
        className="location-map"
        role="region"
        aria-label="Choose weather location on map"
        aria-describedby="map-help"
      />
      <div className="location-controls">
        <button type="button" className="text-button" disabled={disabled} onClick={chooseCenter}>
          Use map center
        </button>
        <span role="status">
          {point ? `Selected point: ${point.latitude.toFixed(4)}, ${point.longitude.toFixed(4)}` : "No point selected"}
        </span>
      </div>
      <p className="map-hint">Use arrow keys to move the map, then choose Use map center.</p>
      {tileError && <p role="alert">Map tiles could not load. Check your connection and reload the page.</p>}
    </section>
  );
}
