"""The Holiday themes option."""
import json
import os
import tempfile
import unittest
from datetime import date
from unittest import mock

import client
import togetherogue
from game import seasons, settings

HALLOWEEN = date(2030, 10, 31)


def rows_of(console):
    return "\n".join("".join(chr(c) for c in console.rgb["ch"][:, y]) for y in range(console.height))


class FakeContext:
    def present(self, console, keep_aspect=True):
        pass


class OptionTests(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch("game.seasons.date")
        self.addCleanup(patcher.stop)
        patcher.start().today.return_value = HALLOWEEN
        saver = mock.patch("togetherogue.settings.save")   # never touch the real settings file
        self.addCleanup(saver.stop)
        self.saved = saver.start()

    def app(self, themes="On"):
        return togetherogue.App(FakeContext(), client.new_console(), dict(settings.DEFAULTS, holiday_themes=themes))

    def script(self, app, *actions):
        """Answers the app's screens in order, and keeps each form."""
        forms, answers = [], iter(actions)

        def show(form, extra=None, timeout=None):
            forms.append(form)
            return next(answers)
        app.show = show
        return forms

    def test_on_by_default(self):
        self.assertEqual(settings.DEFAULTS["holiday_themes"], "On")

    def test_off_means_no_theme_even_on_the_day(self):
        self.assertIsNone(self.app("Off").season_fn())

    def test_on_follows_the_date(self):
        self.assertEqual(self.app("On").season_fn(), "halloween")

    def test_title_greeting_follows_it(self):
        for themes, title in (("Off", ""), ("On", "Happy Halloween!")):
            app = self.app(themes)
            forms = self.script(app, "quit")
            app.main_menu()
            self.assertEqual(forms[0].title, title)

    def test_title_updates_after_changing_the_option(self):
        app = self.app("Off")
        forms = self.script(app, "options", "save", "quit")
        titles = []
        real_options = app.options

        def options():
            real_options()
        app.options = options
        real_show = app.show

        def show(form, extra=None, timeout=None):
            titles.append(form.title)
            if form.title == "Options":
                form.rows[1].value = "On"
            return real_show(form, extra, timeout)
        app.show = show
        app.main_menu()
        self.assertEqual(titles, ["", "Options", "Happy Halloween!"])
        self.assertEqual(app.config["holiday_themes"], "On")
        self.saved.assert_called()

    def test_options_screen_shows_it(self):
        app = self.app()
        forms = self.script(app, "back")
        app.options()
        forms[0].draw(app.console)
        text = rows_of(app.console)
        self.assertIn("Holiday themes", text)
        self.assertIn("< On >", text)
        self.assertEqual(forms[0].rows[1].choices, ("On", "Off"))

    def test_changing_it_doesnt_reopen_the_window(self):
        app = self.app("Off")
        self.script(app, "save")
        app.show = lambda form, extra=None, timeout=None: (form.rows[1].__setattr__("value", "On"), "save")[1]
        app.options()                          # FontChanged would be raised if it did
        self.assertEqual(app.config["holiday_themes"], "On")

    def test_host_and_server_tool_both_obey_it(self):
        for screen in ("host_game", "server_tool"):
            for themes, expected in (("Off", None), ("On", "halloween")):
                app = self.app(themes)
                self.script(app, "go", "back")
                with mock.patch("togetherogue.ServerRunner") as runner:
                    runner.return_value.start.side_effect = OSError
                    getattr(app, screen)()
                self.assertEqual(runner.call_args.kwargs["season_fn"](), expected, (screen, themes))

    def test_worlds_built_with_it_are_plain_or_themed(self):
        from server import ServerRunner
        for themes, expected in (("Off", None), ("On", "halloween")):
            self.assertEqual(ServerRunner(0, season_fn=self.app(themes).season_fn).world.season, expected)

    def test_the_theme_setting_survives_new_runs(self):
        from game.world import World
        app = self.app("Off")
        w = World(1, season_fn=app.season_fn)
        w.join("A")
        w.reset_run()
        self.assertIsNone(w.season)

    def test_saved_settings_from_older_versions_get_the_default(self):
        self.assertEqual(settings.load("Z:/no/such/file.json")["holiday_themes"], "On")

    def test_the_old_setting_is_dropped(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "settings.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"hide_holidays": "On"}, f)
            loaded = settings.load(path)
        self.assertNotIn("hide_holidays", loaded)
        self.assertEqual(loaded["holiday_themes"], "On")


class SeasonModuleTests(unittest.TestCase):
    def test_the_dates_themselves_are_unchanged(self):
        self.assertEqual(seasons.active_season(HALLOWEEN), "halloween")


if __name__ == "__main__":
    unittest.main()
