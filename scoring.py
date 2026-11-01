"""Pure winner selection generated on local Metal, corrected against its contract."""
import math

def choose_winner(a_minutes: float, b_minutes: float) -> str:
    if isinstance(a_minutes, bool) or isinstance(b_minutes, bool) or not isinstance(a_minutes, (int, float)) or not isinstance(b_minutes, (int, float)) or not math.isfinite(a_minutes) or not math.isfinite(b_minutes) or a_minutes <= 0 or b_minutes <= 0:
        raise ValueError('a_minutes and b_minutes must be finite positive numbers, not boolean')
    if math.isclose(a_minutes, b_minutes, rel_tol=1e-9, abs_tol=0.0):
        return 'tie'
    return 'a' if a_minutes > b_minutes else 'b'


def signal_receipt(label: str, signal: dict) -> str:
    return f"{label}: Q={signal['q']:g}, f={signal['frequency_hz']:g}Hz, 1% at {signal['ringing_minutes']:.2f}min"
