"""Manual modes preserve the same total ordered messages across boundaries."""
from tests.helpers import ReplayCase

class StepModeTests(ReplayCase):
    def test_all_modes_and_drivers_send_identical_trace_once(self):
        from liminal_desk_cli.replay.engine import Replay
        for mode,driver in [('driver',0),('driver',1),('timestamp',0),('message',1)]:
            with self.subTest(mode=mode,driver=driver):
                self.publisher.sent.clear()
                self.replay=Replay(self.schedule,self.publisher,['machine','sensor'],self.clock)
                self.replay.step_mode,self.replay.driver=mode,driver
                self.replay.start('step')
                while self.replay.state!='Completed':
                    self.replay.next();self.drain()
                self.assertEqual(self.replay.counts,[36,2644])
                self.assertEqual(len(self.publisher.sent),2680)
                self.assertEqual([p['timestamp_ms']-self.replay.epoch for _,p in self.publisher.sent],
                                 [e.at for e in self.schedule.events])
                self.assertEqual(sum(len(b.sent) for b in self.replay.history),2680)
                if mode=='message':
                    self.assertEqual(len(self.replay.history),2680)
                elif mode=='timestamp' or driver==1:
                    self.assertEqual(len(self.replay.history),661)

    def test_preview_keeps_machine_first_ties_with_sensor_driver(self):
        target,batch=self.schedule.preview(0,1,'driver')
        self.assertEqual(target,0)
        self.assertEqual([e.stream for e in batch],[0,0,1,1,1,1])
        self.assertEqual(self.schedule.preview(6,1,'driver')[0],100)
