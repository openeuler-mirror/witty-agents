"""Fixed state machine for the vLLM benchmark workflow.

Loads the state machine from workflow/benchmark.yaml (via PyYAML if installed,
otherwise a small built-in parser). Persists the current state to a JSON file
so each CLI invocation can enforce valid transitions deterministically.
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.common import ok, err, now_iso, write_json_atomic  # noqa: E402


def _strip_comment(line):
    idx = line.find("#")
    return line[:idx] if idx != -1 else line


def parse_simple_yaml(text):
    """Parse the constrained block-style YAML used by benchmark.yaml."""
    data = {"states": {}, "transitions": []}
    section = None
    current_state = None
    current_trans = None

    for raw in text.splitlines():
        line = _strip_comment(raw).rstrip()
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip(" "))
        content = line.strip()

        if indent == 0:
            current_state = None
            current_trans = None
            if content.startswith("name:"):
                data["name"] = content.split(":", 1)[1].strip()
            elif content.startswith("initial:"):
                data["initial"] = content.split(":", 1)[1].strip()
            elif content.startswith("states:"):
                section = "states"
            elif content.startswith("transitions:"):
                section = "transitions"
        elif indent == 2 and section == "states":
            if content.endswith(":"):
                current_state = content[:-1].strip()
                data["states"][current_state] = {}
                current_trans = None
        elif indent == 4 and section == "states" and current_state:
            k, _, v = content.partition(":")
            data["states"][current_state][k.strip()] = v.strip()
        elif indent == 2 and section == "transitions":
            if content.startswith("- "):
                rest = content[2:].strip()
                k, _, v = rest.partition(":")
                current_trans = {k.strip(): v.strip()}
                data["transitions"].append(current_trans)
            else:
                k, _, v = content.partition(":")
                if current_trans is not None:
                    current_trans[k.strip()] = v.strip()
        elif indent == 4 and section == "transitions" and current_trans:
            k, _, v = content.partition(":")
            current_trans[k.strip()] = v.strip()

    return data


def load_definition(path=None):
    if path is None:
        path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "workflow", "benchmark.yaml",
        )
    text = None
    try:
        with open(path, "r") as f:
            text = f.read()
    except OSError:
        text = None

    if text is None:
        raise ValueError("workflow definition is missing or invalid: %s" % path)

    try:
        import yaml  # noqa: WPS433 - optional dependency
        loaded = yaml.safe_load(text)
        if isinstance(loaded, dict) and loaded.get("states"):
            return loaded
    except ImportError:
        pass
    except Exception:  # noqa: BLE001 - fall through to minimal parser
        pass

    parsed = parse_simple_yaml(text)
    return parsed if parsed.get("states") else {}


class Workflow:
    def __init__(self, state_path, definition=None):
        self.state_path = state_path
        self.definition = definition or load_definition()
        self.meta = {}
        self.state = self._load()

    def _load(self):
        try:
            with open(self.state_path, "r") as f:
                data = json.load(f)
            self.meta = data.get("meta", {k: v for k, v in data.items()
                                          if k not in ("state", "updated_at")}) or {}
            return data.get("state", self.initial())
        except FileNotFoundError:
            self.meta = {}
            return self.initial()

    def _save(self):
        os.makedirs(os.path.dirname(self.state_path), exist_ok=True)
        self.meta["history"] = (self.meta.get("history") or [])[-50:]
        write_json_atomic(self.state_path, {
            "state": self.state, "updated_at": now_iso(), "meta": self.meta})

    def initial(self):
        return self.definition.get("initial", "IDLE")

    def current(self):
        return self.state

    def state_type(self, state=None):
        s = state or self.state
        return self.definition.get("states", {}).get(s, {}).get("type")

    def allowed_events(self):
        return [t["event"] for t in self.definition.get("transitions", [])
                if t.get("from") == self.state]

    def transition(self, event):
        for t in self.definition.get("transitions", []):
            if t.get("from") == self.state and t.get("event") == event:
                previous = self.state
                self.state = t["to"]
                hist = self.meta.get("history") or []
                hist.append({"from": previous, "event": event,
                             "to": self.state, "ts": now_iso()})
                self.meta["history"] = hist[-50:]
                self._save()
                return ok({"state": self.state, "previous": previous,
                           "event": event})
        return err("invalid transition", {
            "state": self.state, "event": event,
            "allowed": self.allowed_events(),
        })

    def set_meta(self, **kwargs):
        self.meta.update(kwargs)
        self._save()
        return ok({"meta": self.meta})

    def reset(self):
        self.state = self.initial()
        self.meta = {}
        self._save()
        return ok({"state": self.state})


if __name__ == "__main__":
    import sys
    wf = Workflow(sys.argv[1] if len(sys.argv) > 1 else "/tmp/wf-state.json")
    print(json.dumps({
        "state": wf.current(),
        "allowed": wf.allowed_events(),
    }, indent=2))
