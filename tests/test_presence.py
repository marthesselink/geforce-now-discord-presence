from pathlib import Path
import runpy
from tempfile import TemporaryDirectory
import unittest


helper = runpy.run_path(str(Path(__file__).resolve().parents[1] / "geforce-discord.py"))
StreamLog = helper["StreamLog"]
LAUNCH = helper["STREAM_LAUNCH"]
FIRST_FRAME = helper["FIRST_FRAME"]
STOP = helper["STOP_EVENTS"][0]


class StreamLogTest(unittest.TestCase):
    def test_requires_launch_metadata_and_first_frame(self):
        stream = StreamLog(None)
        stream.process('"appName": "Unrelated metadata"')
        stream.process(FIRST_FRAME)
        self.assertIsNone(stream.session)

        stream.process(LAUNCH)
        stream.process('"appName": "Example Game"')
        stream.process('"appName": "Unrelated metadata"')
        self.assertIsNone(stream.session)
        stream.process(FIRST_FRAME)
        self.assertEqual(stream.session[0], "Example Game")
        stream.process(STOP)
        self.assertIsNone(stream.session)

    def test_partial_line_and_log_rotation(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "console.log"
            path.write_text(f'{LAUNCH}\n"appName": "Example Game"\n{FIRST_FRAME}', encoding="utf-8")
            stream = StreamLog(path)
            stream.update()
            self.assertIsNone(stream.session)

            with path.open("a", encoding="utf-8") as log:
                log.write("\n")
            stream.update()
            self.assertEqual(stream.session[0], "Example Game")

            path.rename(path.with_suffix(".old"))
            path.write_text("Application restarted\n", encoding="utf-8")
            stream.update()
            self.assertIsNone(stream.session)


class CatalogTest(unittest.TestCase):
    def test_canonical_name_wins_and_ambiguous_alias_is_skipped(self):
        index = helper["index_games"]([
            {"id": "123", "name": "Example™ Game", "aliases": ["Example", "Shared"]},
            {"id": "456", "name": "Other Game", "aliases": ["Example Game", "Shared"]},
        ])
        self.assertEqual(index["examplegame"], "123")
        self.assertEqual(index["example"], "123")
        self.assertNotIn("shared", index)


if __name__ == "__main__":
    unittest.main()
