"""Headless interaction tests exercise the real Textual screens and replay engine."""
import asyncio
import json
from pathlib import Path
import tempfile
import unittest
from textual.widgets import DataTable, Input, Select, Static, TabbedContent
from liminal_desk_cli.config import parse_args
from liminal_desk_cli.replay.schedule import Schedule
from liminal_desk_cli.ui.app import DeskApp
from liminal_desk_cli.ui.screens import TracePicker, Connections

ROOT = Path(__file__).resolve().parent.parent

class TextualTests(unittest.IsolatedAsyncioTestCase):
    def make_app(self, *argv):
        _, args = parse_args(['--dry-run', *argv])
        return DeskApp(args, Schedule([args.machine,args.sensor]),
                       preferences_path=Path(tempfile.gettempdir())/'liminal-ui-tests'/'preferences.json')

    async def until(self, condition):
        for _ in range(400):
            if condition():
                return
            await asyncio.sleep(.01)
        self.fail('UI operation did not complete')

    async def test_step_scroll_filters_inspection_history_and_tabs(self):
        app = self.make_app()
        async with app.run_test(size=(140,42)) as pilot:
            await pilot.press('c','d','n')
            await self.until(lambda: app.replay.state == 'Step ready' and app.replay.counts == [2,4])
            await pilot.press('n')
            await self.until(lambda: app.replay.state == 'Step ready' and app.replay.counts == [4,44])
            await pilot.pause(.1)
            table = app.query_one('#events',DataTable)
            self.assertEqual(table.row_count,42)
            table.focus()
            await pilot.press('ctrl+end')
            # DataTable's end action reaches the last row, independent of viewport.
            self.assertEqual(table.cursor_row,41)
            await pilot.press('enter')
            self.assertTrue(app.query_one('#inspector').display)
            self.assertIn('timestamp_ms',str(app.query_one('#inspection',Static).render()))
            await pilot.press('escape')
            app.query_one('#kind-filter',Select).value = 'vibration'
            await pilot.pause(.15)
            self.assertEqual(table.row_count,20)
            keys=[key.value for key in table.rows]
            self.assertNotEqual(keys,list(map(str,range(1,21))))
            app.query_one('#kind-filter',Select).value = '*'
            await pilot.pause(.1)
            table.move_cursor(row=30)
            tabs=app.query_one('#tabs',TabbedContent)
            tabs.active='received';await pilot.pause(.1)
            tabs.active='sent';await pilot.pause(.1)
            self.assertEqual(table.cursor_row,30)
            app._select_batch(1)
            self.assertEqual(table.row_count,6)
            app._select_batch(2)
            self.assertEqual(table.cursor_row,30)
            await pilot.press('n')
            await self.until(lambda:app.replay.state=='Step ready' and len(app.replay.history)==3)
            app._select_batch(1)
            self.assertEqual(table.row_count,6)
        self.assertFalse(app.broker.connected)

    async def test_picker_validates_before_replacement_and_cancel(self):
        app=self.make_app()
        with tempfile.TemporaryDirectory() as folder:
            bad=Path(folder)/'broken.json';bad.write_text('{}')
            async with app.run_test(size=(120,36)) as pilot:
                await pilot.press('o');await pilot.pause(.1)
                self.assertIsInstance(app.screen,TracePicker)
                picker=app.screen
                picker.validate_path(bad);await pilot.pause(.2)
                self.assertIsNone(picker.validated)
                self.assertTrue(picker.query_one('#file-load').disabled)
                self.assertEqual(app.paths[0],app.args.machine)
                picker.validate_path(app.paths[0]);await pilot.pause(.2)
                self.assertIsNotNone(picker.validated)
                self.assertFalse(picker.query_one('#file-load').disabled)
                await pilot.click('#file-load');await pilot.pause(.1)
                self.assertNotIsInstance(app.screen,TracePicker)
                self.assertEqual(app.schedule.totals,[36,2644])
                await pilot.press('o','escape')
                self.assertNotIsInstance(app.screen,TracePicker)

    async def test_connections_validation_and_tcp_apply(self):
        app=self.make_app()
        async with app.run_test(size=(120,40)) as pilot:
            await pilot.press('b');await pilot.pause(.1)
            screen=app.screen;self.assertIsInstance(screen,Connections)
            screen.query_one('#port-0',Input).value='0'
            screen.save();await pilot.pause(.1)
            self.assertIs(app.screen,screen)
            self.assertEqual(app.args.streams[0].port,1883)
            for i in (0,1):
                screen.query_one(f'#transport-{i}',Select).value='tcp'
                screen.query_one(f'#port-{i}',Input).value=str(8080+i)
            screen.save();await pilot.pause(.1)
            self.assertEqual([s.transport for s in app.args.streams],['tcp','tcp'])
            await pilot.press('c','d','n')
            await self.until(lambda:app.replay.counts==[2,4])
            await pilot.pause(.1)
            app.query_one('#events',DataTable).focus()
            await pilot.press('enter')
            self.assertIn('Simulated',str(app.query_one('#inspection',Static).render()))

    async def test_driver_and_single_message_step(self):
        app=self.make_app()
        async with app.run_test(size=(100,30)) as pilot:
            app.query_one('#driver',Select).value=1
            app.query_one('#step-mode',Select).value='message'
            await pilot.pause(.1)
            await pilot.press('c','d','n')
            await self.until(lambda:app.replay.index==1 and app.replay.state=='Step ready')
            self.assertEqual(app.replay.driver,1)
            self.assertEqual(app.replay.counts,[1,0])
            app.query_one('#step-mode',Select).value='timestamp'
            await pilot.pause(.1)
            await pilot.press('n')
            await self.until(lambda:app.replay.state=='Step ready' and app.replay.index==6)
            self.assertEqual(app.replay.counts,[2,4])

    async def test_receive_does_not_jump_selection_and_small_terminal(self):
        app=self.make_app()
        async with app.run_test(size=(80,24)) as pilot:
            # Real transport-independent receive records, including non-JSON text.
            for i in range(1,30):
                app.broker.record_log.append((i,'12:00:00','topic',json.dumps({'type':'lidar','value':i}),False))
            app._refresh_received()
            table=app.query_one('#received-events',DataTable)
            table.move_cursor(row=3)
            before=table.cursor_row
            app.broker.record_log.append((30,'12:00:01','topic','not json',True))
            app._refresh_received()
            self.assertEqual(table.cursor_row,before)
            self.assertEqual(table.row_count,30)
            app.query_one('#tabs',TabbedContent).active='received'
            await pilot.pause(.1)
            table.focus();await pilot.press('enter')
            self.assertIn('Received event',str(app.query_one('#inspection',Static).render()))
            await pilot.press('escape','q')
