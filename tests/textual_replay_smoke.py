"""Optional full-duration Textual + mixed MQTT/TCP replay on isolated receivers."""
import asyncio
from liminal_desk_cli.config import parse_args
from liminal_desk_cli.replay.schedule import Schedule
from liminal_desk_cli.ui.app import DeskApp
from tests.test_mqtt_integration import LoopbackMqtt
from tests.test_tcp_integration import FrameServer

async def main():
    mqtt, tcp = LoopbackMqtt(), FrameServer()
    try:
        _, args = parse_args(['--host','127.0.0.1','--port',str(mqtt.port),
                              '--sensor-transport','tcp','--sensor-port',str(tcp.port)])
        schedule = Schedule([args.machine,args.sensor])
        app = DeskApp(args,schedule)
        async with app.run_test(size=(140,42)):
            app.action_connect()
            for _ in range(500):
                if app.broker.ready:
                    break
                await asyncio.sleep(.01)
            assert app.broker.ready, app.broker.state
            app.action_run()
            for _ in range(8500):
                if app.replay.state in ('Completed','Error'):
                    break
                await asyncio.sleep(.01)
            assert app.replay.state == 'Completed', (app.replay.state,app.replay.error)
            assert app.replay.counts == [36,2644],app.replay.counts
            assert len(mqtt.messages) == 36,len(mqtt.messages)
            assert len(tcp.messages) == 2644,len(tcp.messages)
            assert sum(len(b.sent) for b in app.replay.history)==2680
            assert not mqtt.errors,mqtt.errors
            assert not tcp.errors,tcp.errors
            print(f'PASS: full-duration Textual mixed replay; 36 MQTT + 2644 TCP; lag {app.replay.max_late:.1f} ms')
    finally:
        mqtt.close();tcp.close()

if __name__ == '__main__':
    asyncio.run(main())
