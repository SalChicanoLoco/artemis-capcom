"""Pure scenario mathematics. No forecasts or operational clearance."""
import math

def finite(value, name):
    value = float(value)
    if not math.isfinite(value):
        raise ValueError(name + " must be finite")
    return value


def radiated_energy(magnitude):
    magnitude = finite(magnitude, "Mw")
    if not 0 < magnitude <= 7:
        raise ValueError("Mw must satisfy 0 < Mw <= 7")
    return 10 ** (4.8 + 1.5 * magnitude)


def coda_envelope(t, q=4200, frequency=1.0, alpha=0.5, a0=1.0):
    t, q, frequency, alpha, a0 = [finite(v, "coda parameter") for v in (t, q, frequency, alpha, a0)]
    if t <= 0 or not 3000 <= q <= 5000 or frequency <= 0 or alpha < 0 or a0 < 0:
        raise ValueError("Require t>0, Q=3000..5000, f>0, alpha>=0, A0>=0")
    return a0 * t ** (-alpha) * math.exp(-math.pi * frequency * t / q)


def ringing_minutes(q=4200, frequency=1.0, alpha=0.5, threshold=0.01):
    threshold = finite(threshold, "threshold")
    if not 0 < threshold < 1:
        raise ValueError("Require 0 < threshold < 1")
    target = coda_envelope(1, q, frequency, alpha) * threshold
    low, high = 1.0, 2.0
    while coda_envelope(high, q, frequency, alpha) > target:
        high *= 2
    for _ in range(64):
        mid = (low + high) / 2
        if coda_envelope(mid, q, frequency, alpha) > target:
            low = mid
        else:
            high = mid
    return high / 60


def simulate_moonquake(magnitude):
    energy = radiated_energy(magnitude)
    # E/(4*pi*r²*duration) = rho*v*ground_velocity²; a=2*pi*f*velocity.
    # Uniform spherical radiation, no attenuation/site effects; scenario only.
    assumptions = {"distance_m": 10000, "density_kg_m3": 3000,
                   "wave_speed_m_s": 3000, "source_duration_s": 20,
                   "frequency_hz": 1.0, "lunar_g_m_s2": 1.62}
    velocity = math.sqrt(energy / (4 * math.pi * 10000**2 * 3000 * 3000 * 20))
    pga = 2 * math.pi * velocity / 1.62
    duration = ringing_minutes()
    return {"magnitude": float(magnitude), "energy_j": energy, "q": 4200,
            "frequency_hz": 1.0, "alpha": 0.5, "a0": 1.0,
            "ringing_minutes": duration, "threshold_fraction_at_1s": 0.01,
            "pga_lunar_g": pga, "pga_assumptions": assumptions,
            "hab_status": "UNASSESSED — no structural model",
            "message": (f"[COMPUTED] Simulated Mw {float(magnitude):g}: E_R={energy:.6e} J; "
                        f"Q=4200, 1% coda at {duration:.2f} min (f=1Hz, alpha=0.5). "
                        f"[INFERRED] Scenario PGA={pga:.4g} lunar g at 10km; hab unassessed.")}


