import { useEffect, useRef, useState } from "react";
import { listStations, nearbyStations, type StationCatalog } from "../lib/api";
import { RequestScope } from "../lib/requestScope";

export function useStationCatalog() {
  const [catalog, setCatalog] = useState<StationCatalog | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [nearby, setNearby] = useState(false);
  const requests = useRef(new RequestScope());

  useEffect(() => {
    const scope = requests.current;
    const controller = scope.begin();
    void listStations(controller.signal).then(result => {
      if (scope.owns(controller)) setCatalog(result);
    }).catch(() => {
      if (scope.owns(controller)) setError("Stations could not load. Please try again.");
    }).finally(() => { scope.finish(controller); });
    return () => scope.cancel();
  }, []);

  async function showAll() {
    const scope = requests.current;
    const controller = scope.begin();
    setBusy(true);
    setError("");
    try {
      const result = await listStations(controller.signal);
      if (scope.owns(controller)) { setCatalog(result); setNearby(false); }
    } catch {
      if (scope.owns(controller)) setError("Stations could not load. Please try again.");
    } finally {
      if (scope.finish(controller)) setBusy(false);
    }
  }

  function findNearby() {
    if (!navigator.geolocation) {
      setError("Location is unavailable in this browser. Search by station or county below.");
      return;
    }
    const scope = requests.current;
    const controller = scope.begin();
    setBusy(true);
    setError("");
    navigator.geolocation.getCurrentPosition(position => {
      if (!scope.owns(controller)) return;
      void nearbyStations({ latitude: position.coords.latitude, longitude: position.coords.longitude }, controller.signal)
        .then(result => {
          if (scope.owns(controller)) { setCatalog(result); setNearby(true); }
        }).catch(() => {
          if (scope.owns(controller)) setError("Nearby stations could not load. You can still choose a station below.");
        }).finally(() => { if (scope.finish(controller)) setBusy(false); });
    }, failure => {
      if (!scope.finish(controller)) return;
      setBusy(false);
      setError(failure.code === 1 ? "Location access was declined. You can still search and choose a station." :
        "Your location could not be found. You can still search and choose a station.");
    }, { enableHighAccuracy: false, timeout: 10000, maximumAge: 60000 });
  }

  function cancel() {
    requests.current.cancel();
    setBusy(false);
  }

  return { catalog, busy, error, nearby, showAll, findNearby, cancel };
}
