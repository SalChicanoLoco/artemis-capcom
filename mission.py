"""A timed chat challenge scored against a disclosed mathematical model."""
import copy
import time
from physics import ringing_minutes
from scoring import choose_winner, signal_receipt

SCENARIOS = (
    ("THE LONG ECHO", "Same frequency. Different Q. Which signal survives longer?", (3000, 1), (5000, 1)),
    ("THE FREQUENCY TRAP", "A higher Q is not the whole story. Watch the frequency.", (5000, 2), (3000, .5)),
    ("LOW AND SLOW", "One signal sheds energy faster. Pick your crew's survivor.", (5000, .5), (3000, 2)),
)


def award_points(guesses, correct, scores):
    """Adapted from local mlx-metal candidate; contract corrected and tested."""
    if correct not in ("a", "b", "tie"):
        raise ValueError("Invalid winning choice")
    result = dict(scores)
    for user, vote in guesses.items():
        if not isinstance(user, str) or not user or vote not in ("a", "b"):
            raise ValueError("Expected user names and a/b votes")
        points = 50 if correct == "tie" else 100 if vote == correct else 0
        result[user] = result.get(user, 0) + points
    return result


class Mission:
    def __init__(self, clock=time.monotonic, wall=time.time, voting_seconds=20, replay_seconds=8):
        self.clock, self.wall = clock, wall
        self.voting_seconds, self.replay_seconds = voting_seconds, replay_seconds
        self.round = None
        self.round_id = 0
        self.scores = {}
        self.votes = {}
        self.deadline = 0

    def start(self):
        if self.round and self.round["phase"] in ("voting", "replay"):
            raise ValueError("Round already active; finish it or !reset")
        title, hint, a, b = SCENARIOS[self.round_id % len(SCENARIOS)]
        self.round_id += 1
        self.votes = {}
        self.deadline = self.clock() + self.voting_seconds
        self.round = {"id": self.round_id, "title": title, "hint": hint, "phase": "voting",
                      "a": {"q": a[0], "frequency_hz": a[1]},
                      "b": {"q": b[0], "frequency_hz": b[1]},
                      "closes_at": self.wall() + self.voting_seconds,
                      "voting_seconds": self.voting_seconds, "replay_seconds": self.replay_seconds,
                      "winner": None, "explanation": None}
        return f"[COMPUTED] MISSION {self.round_id}: {title}. Which signal rings longer? !vote a or !vote b. {self.voting_seconds:g}s to choose. Simulation only."

    def vote(self, user, choice):
        if not self.round or self.round["phase"] != "voting" or self.clock() >= self.deadline:
            raise ValueError("Voting is closed; wait for the next !mission")
        if choice not in ("a", "b"):
            raise ValueError("Choose !vote a or !vote b")
        if not user:
            raise ValueError("A viewer identity is required to vote")
        if user not in self.votes and (len(self.votes) >= 2000 or (user not in self.scores and len(self.scores) + sum(u not in self.scores for u in self.votes) >= 5000)):
            raise ValueError("This session's participant capacity is reached")
        self.votes[user] = choice
        return f"[COMPUTED] {user}: signal {choice.upper()} selected. One vote per viewer; latest choice counts."

    def lock(self):
        if not self.round or self.round["phase"] != "voting":
            raise ValueError("No round is accepting votes")
        self.round.update(phase="replay", replay_started_at=self.wall())
        self.deadline = self.clock() + self.replay_seconds
        return f"[COMPUTED] Votes locked. Comparing two synthetic envelopes; reveal in {self.replay_seconds:g} seconds."

    def reset(self):
        self.round = None
        self.votes = {}
        return "[REFERENCE] Active mission cancelled. Session scores retained."

    def tick(self):
        if not self.round or self.clock() < self.deadline:
            return None
        if self.round["phase"] == "voting":
            return self.lock()
        if self.round["phase"] != "replay":
            return None
        a, b = self.round["a"], self.round["b"]
        for signal in (a, b):
            signal["ringing_minutes"] = ringing_minutes(signal["q"], signal["frequency_hz"])
        winner = choose_winner(a["ringing_minutes"], b["ringing_minutes"])
        self.scores = award_points(self.votes, winner, self.scores)
        explanation = (signal_receipt("A", a) + "; " + signal_receipt("B", b) + ". "
                       "A(t)=t^-0.5 exp(-pi*f*t/Q); threshold=1% of A(1s).")
        self.round.update(phase="revealed", winner=winner, explanation=explanation)
        return f"[COMPUTED] {'TIE' if winner == 'tie' else 'SIGNAL ' + winner.upper() + ' WINS'}! {explanation} Correct picks +100 points."

    def snapshot(self):
        current = copy.deepcopy(self.round)
        if current:
            current["counts"] = {c: sum(v == c for v in self.votes.values()) for c in ("a", "b")}
            current["participants"] = len(self.votes)
        return {"round": current, "leaderboard": [
            {"user": user, "points": points}
            for user, points in sorted(self.scores.items(), key=lambda row: (-row[1], row[0]))[:8]]}
