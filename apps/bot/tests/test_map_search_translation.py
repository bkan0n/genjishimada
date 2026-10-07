"""Unknown map names remain usable in the Chinese search formatter."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from extensions.map_search import CNTranslatedFilteredFormatter


class MapLabel:
    def __init__(self, name):
        self.name = name

    def to_format_dict(self):
        return {"Map": self.name}


def test_known_map_uses_chinese_translation():
    assert "花村" in CNTranslatedFilteredFormatter(MapLabel("Hanamura")).format()


def test_new_map_keeps_its_name():
    assert "Watchpoint: Grimsvötn" in CNTranslatedFilteredFormatter(MapLabel("Watchpoint: Grimsvötn")).format()
