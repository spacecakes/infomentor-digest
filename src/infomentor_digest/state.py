"""Remember which facts each channel reported, so a later run stays quiet about them.

The keys are kept per channel. A channel that failed is offered the same facts
again on the next run, while the channels that took them stay quiet.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Store:
    path: Path
    reported: dict[str, dict[str, set[str]]] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path) -> "Store":
        if not path.exists():
            return cls(path=path)
        raw = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            path=path,
            reported={
                channel: {pupil: set(keys) for pupil, keys in pupils.items()}
                for channel, pupils in raw.get("channels", {}).items()
            },
        )

    def keys(self, channel: str, pupil_id: int) -> set[str]:
        return self.reported.get(channel, {}).get(str(pupil_id), set())

    def keys_anywhere(self, pupil_id: int) -> set[str]:
        """What any channel reported. A dry run reads this, having no channel of its own."""
        return set().union(*(self.keys(channel, pupil_id) for channel in self.reported))

    def knows(self, channel: str, pupil_id: int) -> bool:
        """A pupil a channel never reported gets seeded instead of reported, to avoid a flood."""
        return str(pupil_id) in self.reported.get(channel, {})

    def add(self, channel: str, pupil_id: int, keys: set[str]) -> None:
        self.reported.setdefault(channel, {}).setdefault(str(pupil_id), set()).update(keys)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "channels": {
                channel: {pupil: sorted(keys) for pupil, keys in pupils.items()}
                for channel, pupils in self.reported.items()
            }
        }
        self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
