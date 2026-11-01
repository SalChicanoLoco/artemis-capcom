"""Command validation, deterministic receipts and bounded query cache."""
import copy
import json
from pathlib import Path
import time
from physics import simulate_moonquake
from model_slot import MLXModelSlot
from mission import Mission
ROOT = Path(__file__).resolve().parent

class CapCom:
    def __init__(self, model=None, clock=time.monotonic, sites_path=ROOT / "fixtures/sites.json"):
        self.catalog = json.loads(Path(sites_path).read_text())
        self.sites = self.catalog["sites"]
        self.model = model if model is not None else MLXModelSlot()
        self.clock = clock
        self.cache = {}
        self.counters = {"computations": 0, "cache_hits": 0, "calls_avoided": 0, "errors": 0}
        self.last_site = None
        self.last_quake = None
        self.last_aoi = None
        self.sequence = 0
        self.mission = Mission(clock=clock)

    def landing(self, key):
        if key not in self.sites:
            raise ValueError("Unknown site; choose " + ", ".join(self.sites))
        site = dict(self.sites[key])
        site.update(site=key, elevated_slip_risk=site["scarp_km"] < 10,
                    slope_flag=site["slope_deg"] > 15, provenance=self.catalog["provenance"])
        site["message"] = (f"[REFERENCE] [FIXTURE] ILLUSTRATIVE fixture: {site['name']}, slope {site['slope_deg']:g} deg, "
                           f"scarp {site['scarp_km']:g}km, cold-trap scenario={site['cold_trap']}. "
                           f"[COMPUTED] Scarp <10km={site['elevated_slip_risk']}; slope >15deg={site['slope_flag']}. "
                           "[INFERRED] Elevated slip potential near scarps; no landing clearance or confirmed ice.")
        return site

    def context(self):
        text = ("[REFERENCE] Dry lunar materials can sustain long seismic codas; scenario Q=3000..5000. "
                "[COMPUTED] E_R=10^(4.8+1.5*Mw) J; A(t)=A0*t^-alpha*exp(-pi*f*t/Q). "
                "[INFERRED] Scarp proximity is a screening heuristic, not a quake prediction.")
        if self.last_site:
            text += f" [REFERENCE] Last illustrative site: {self.last_site['name']}; scarp {self.last_site['scarp_km']}km."
        if self.last_quake:
            text += f" [COMPUTED] Last simulated energy: {self.last_quake['energy_j']:.6e} J."
        return text

    def handle(self, line, user="local", commander=False):
        self.sequence += 1
        now = self.clock()
        line = " ".join(str(line).split())
        command, _, argument = line.partition(" ")
        command = command.lower()
        argument = argument if command == "!capcom" else argument.lower()
        # Include current context in CapCom cache keys so a new simulation cannot return stale advice.
        key = (command, argument, self.context() if command == "!capcom" else "",
               self.model.status().get("revision", 0) if command == "!capcom" else 0)
        self.cache = {k: v for k, v in self.cache.items() if now - v[0] < 30}
        game_command = command in ("!mission", "!vote", "!reveal", "!reset", "!help")
        cached = None if game_command else self.cache.get(key)
        if cached:
            result = copy.deepcopy(cached[1])
            self.counters["cache_hits"] += 1
            self.counters["calls_avoided"] += 1
            result.update(cache_hit=True, modelled_energy=0.0)
        else:
            try:
                if len(line) > 600 or (not argument and not game_command):
                    raise ValueError("Supply a command argument (maximum 600 characters)")
                if game_command:
                    if command in ("!mission", "!reveal", "!reset") and not commander:
                        raise ValueError("Only the broadcaster or local director can control rounds")
                    if command == "!mission":
                        message = self.mission.start()
                    elif command == "!vote":
                        message = self.mission.vote(user, argument)
                    elif command == "!reveal":
                        message = self.mission.lock()
                    elif command == "!reset":
                        message = self.mission.reset()
                    else:
                        message = "[REFERENCE] Viewer: !vote a | !vote b, !capcom <question>. Host: !mission, !reveal, !reset. Explore: !landing <site>, !moonquake <Mw>, !aoi <site>."
                    data = {"message": message}
                elif command == "!landing":
                    data = self.landing(argument)
                elif command == "!moonquake":
                    data = simulate_moonquake(argument)
                elif command == "!aoi":
                    site = self.landing(argument)
                    lat, lon = site["lat"], site["lon"]
                    polygon = [[lon - 1, lat - .05], [lon + 1, lat - .05],
                               [lon + 1, lat + .05], [lon - 1, lat + .05], [lon - 1, lat - .05]]
                    data = {"site": argument, "polygon_lon_lat": polygon,
                            "elevated_slip_risk": site["elevated_slip_risk"], "cold_trap": site["cold_trap"],
                            "message": "[COMPUTED] Illustrative AOI bounding polygon (lon,lat). " + site["message"]}
                elif command == "!capcom":
                    context = self.context()
                    answer = self.model.generate(argument, context)
                    data = {"answer_source": "mlx" if answer else "deterministic",
                            "chat_message": answer or context,
                            "message": (answer + " " if answer else "") + context}
                else:
                    raise ValueError("Unknown command; use !landing, !moonquake, !aoi, !capcom")
                result = {"ok": True, "kind": command[1:], "data": data,
                          "message": data["message"], "cache_hit": False,
                          "modelled_energy": None}  # physical model energy use has not been measured
                self.counters["computations"] += 1
                if len(self.cache) >= 256:
                    self.cache.pop(next(iter(self.cache)))
                if not game_command:
                    self.cache[key] = (self.clock(), copy.deepcopy(result))
            except (ValueError, TypeError, OverflowError) as exc:
                self.counters["errors"] += 1
                result = {"ok": False, "kind": "error", "data": {}, "cache_hit": False,
                          "modelled_energy": 0.0, "message": "[REFERENCE] REJECTED: " + str(exc)}
        if result["ok"] and command == "!landing":
            self.last_site = result["data"]
        if result["ok"] and command == "!moonquake":
            self.last_quake = dict(result["data"], simulated_at=time.time())
        if result["ok"] and command == "!aoi":
            self.last_aoi = result["data"]
        result.update(sequence=self.sequence, timestamp=time.time(), counters=dict(self.counters),
                      model=self.model.status(), mission=self.mission.snapshot(), state=copy.deepcopy({
                          "site": self.last_site, "quake": self.last_quake, "aoi": self.last_aoi}))
        return result

    def system_event(self, kind, message):
        """Clock transitions are receipts, not extra viewer computations."""
        self.sequence += 1
        return {"sequence": self.sequence, "timestamp": time.time(), "kind": kind,
                "ok": True, "message": message, "data": {}, "cache_hit": False,
                "modelled_energy": None, "counters": dict(self.counters),
                "model": self.model.status(), "mission": self.mission.snapshot(),
                "state": copy.deepcopy({"site": self.last_site, "quake": self.last_quake, "aoi": self.last_aoi})}


