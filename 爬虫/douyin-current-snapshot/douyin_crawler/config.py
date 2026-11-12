import argparse
from dataclasses import dataclass, field, fields
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


@dataclass
class Config:
    source: str = "feed"
    author: str = ""
    keyword: str = ""
    tag: str = ""
    title_contains: list[str] = field(default_factory=list)
    rules: list[dict] = field(default_factory=list)
    plugins: list[str] = field(default_factory=list)
    source_options: dict = field(default_factory=dict)
    all: bool = False
    limit: int | None = None
    max_scrolls: int | None = None
    max_duration: int | None = None
    max_video_mb: int | None = None
    wait_seconds: float = 4
    login_timeout: int = 600
    output_dir: Path = ROOT / "downloads"
    profile_dir: Path = ROOT / "browser_profile"
    state_dir: Path = ROOT / "runs"
    discover_only: bool = False
    login_only: bool = False
    inspect: bool = False
    export_manifest: Path | None = None
    storage_state: Path | None = None
    browser_channel: str = "msedge"
    download_interval: float = 0

    def validate(self):
        for name in ("source", "author", "keyword", "tag"):
            if not isinstance(getattr(self, name), str):
                raise ValueError(f"{name} must be a string")
        self.author = self.author.strip()
        self.keyword = self.keyword.strip()
        self.tag = self.tag.strip().lstrip("#")
        for name in ("all", "discover_only", "login_only", "inspect"):
            if not isinstance(getattr(self, name), bool):
                raise ValueError(f"{name} must be a JSON boolean")
        if not isinstance(self.source_options, dict):
            raise ValueError("source_options must be an object")
        if self.export_manifest and (self.discover_only or self.login_only or self.inspect):
            raise ValueError("--export-manifest cannot be combined with discover-only, login-only or inspect")
        if self.source == "author" and not self.author:
            raise ValueError("--source author requires --author")
        if self.source == "search" and not self.keyword.strip():
            raise ValueError("--source search requires --keyword")
        if self.source == "hashtag" and not self.tag.strip().lstrip("#"):
            raise ValueError("--source hashtag requires --tag")
        if self.author and self.source != "author":
            raise ValueError("--author requires --source author")
        if self.keyword and self.source != "search":
            raise ValueError("--keyword requires --source search")
        if self.all and self.limit is not None:
            raise ValueError("--all cannot be combined with --limit")
        self.limit = 0 if self.all else (3 if self.limit is None else self.limit)
        self.max_scrolls = self.max_scrolls if self.max_scrolls is not None else (1000 if self.all else 20)
        self.max_duration = self.max_duration if self.max_duration is not None else (0 if self.all else 180)
        self.max_video_mb = self.max_video_mb if self.max_video_mb is not None else (0 if self.all else 100)
        if (not self.all and self.limit < 1) or min(self.max_scrolls, self.max_duration, self.max_video_mb) < 0:
            raise ValueError("limit must be positive; other limits may be 0 but not negative")
        if self.wait_seconds < 1 or self.login_timeout < 1:
            raise ValueError("wait_seconds and login_timeout must be positive")
        if self.download_interval < 0:
            raise ValueError("download_interval must be nonnegative")
        if not isinstance(self.rules, list) or any(not isinstance(rule, dict) for rule in self.rules):
            raise ValueError("rules must be a list of objects")
        for name in ("title_contains", "plugins"):
            value = getattr(self, name)
            if not isinstance(value, list) or any(not isinstance(x, str) or not x.strip() for x in value):
                raise ValueError(f"{name} must be a list of nonempty strings")
        return self


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Discover Douyin videos using configurable sources and filters")
    parser.add_argument("--config", type=Path, help="JSON task file; CLI values override it")
    for name in ("source", "author", "keyword", "tag"):
        parser.add_argument("--" + name)
    for name in ("limit", "max_scrolls", "max_duration", "max_video_mb", "login_timeout"):
        parser.add_argument("--" + name.replace("_", "-"), type=int)
    parser.add_argument("--wait-seconds", type=float)
    parser.add_argument("--download-interval", type=float)
    for name in ("all", "discover_only", "login_only", "inspect"):
        parser.add_argument("--" + name.replace("_", "-"), action="store_true", default=None)
    parser.add_argument("--title-contains", action="append")
    parser.add_argument("--plugin", action="append", dest="plugins")
    parser.add_argument("-o", "--output-dir", type=Path)
    parser.add_argument("--profile-dir", type=Path)
    parser.add_argument("--state-dir", type=Path)
    parser.add_argument("--export-manifest", type=Path, help="Export resolved media jobs without downloading locally")
    parser.add_argument("--storage-state", type=Path)
    parser.add_argument("--browser-channel", help="msedge (local) or chromium (server)")
    args = vars(parser.parse_args(argv))
    config_file = args.pop("config")
    data = {}
    try:
        if config_file:
            data = json.loads(config_file.read_text(encoding="utf-8-sig"))
            if not isinstance(data, dict):
                raise ValueError("Task configuration must be a JSON object")
            unknown = set(data) - {f.name for f in fields(Config)}
            if unknown:
                raise ValueError(f"Unknown configuration keys: {sorted(unknown)}")
            for key in ("output_dir", "profile_dir", "state_dir", "export_manifest", "storage_state"):
                if key in data:
                    data[key] = (config_file.resolve().parent / data[key]).resolve()
        if args["limit"] is not None and args["all"] is None:
            data["all"] = False
        if args["all"]:
            data.pop("limit", None)
        data.update({key: value for key, value in args.items() if value is not None})
        for key in ("output_dir", "profile_dir", "state_dir", "export_manifest", "storage_state"):
            if key in data:
                data[key] = Path(data[key]).resolve()
        return Config(**data).validate()
    except (ValueError, TypeError, OSError) as exc:
        parser.error(str(exc))
