"""Run against an explicitly supplied local Liminal binary, using isolated ports.

python -m tests.liminal_tcp_smoke --liminal /path/to/liminal
"""
import argparse
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import time
from liminal_desk_cli.config import parse_args
from liminal_desk_cli.replay.engine import Replay
from liminal_desk_cli.replay.schedule import Schedule
from liminal_desk_cli.transports.manager import TransportManager
from tests.test_tcp_integration import FrameServer


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--liminal',required=True,type=Path)
    options=parser.parse_args()
    binary=options.liminal.resolve()
    if not binary.is_file():
        parser.error('Liminal binary does not exist')
    root=Path(__file__).resolve().parent.parent
    outputs=[FrameServer(echo=False),FrameServer(echo=False)]
    ports=[]
    # Allocate distinct ephemeral input ports without touching configured services.
    reservations=[socket.socket(),socket.socket()]
    for sock in reservations:
        sock.bind(('127.0.0.1',0));ports.append(sock.getsockname()[1])
    manager=process=None
    try:
        with tempfile.TemporaryDirectory(prefix='liminal-tcp-') as directory:
            base=Path(directory);blocks=[]
            for i,name in enumerate(('machine','sensor')):
                blocks.append(f'''[inputs.{name}]
type = "tcp_input"
output = "{name}_data"
concurrency = {{ type = "thread" }}
channel = {{ type = "broadcast", capacity = 8192 }}
parameters = {{ mode = "server", host = "127.0.0.1", port = {ports[i]}, reconnect = true, reconnect_interval_ms = 25 }}

[outputs.{name}_out]
type = "tcp_output"
inputs = ["{name}_data"]
concurrency = {{ type = "thread" }}
parameters = {{ mode = "client", host = "127.0.0.1", port = {outputs[i].port}, reconnect = true, reconnect_interval_ms = 25 }}
''')
            config=base/'test.toml';config.write_text('\n'.join(blocks))
            for sock in reservations:sock.close()
            with (base/'liminal.log').open('w+') as log:
                process=subprocess.Popen([str(binary),'--config',str(config),'--log-level','info'],stdout=log,stderr=log,env=dict(os.environ,RUST_LOG='info'))
                deadline=time.monotonic()+10
                while time.monotonic()<deadline:
                    text=(base/'liminal.log').read_text()
                    if text.count('TCP server listening')>=2:break
                    if process.poll() is not None:raise AssertionError(text)
                    time.sleep(.01)
                else:raise AssertionError('Liminal did not start both isolated TCP inputs: '+text)
                _,args=parse_args(['--transport','tcp','--host','127.0.0.1','--machine-port',str(ports[0]),'--sensor-port',str(ports[1])])
                manager=TransportManager(args);manager.connect()
                schedule=Schedule([root/'examples/shop_floor'/name for name in ('machine_events.json','sensor_events.json')])
                replay=Replay(schedule,manager,args.topics);replay.start('step')
                deadline=time.monotonic()+30
                while replay.state!='Completed' and time.monotonic()<deadline:
                    if replay.state=='Step ready':replay.next()
                    manager.pump();replay.tick();time.sleep(.001)
                assert replay.state=='Completed',manager.state
                deadline=time.monotonic()+10
                while time.monotonic()<deadline and [len(s.messages) for s in outputs]!=[36,2644]:time.sleep(.01)
                for i,server in enumerate(outputs):
                    actual=[message['payload'] for message in server.messages]
                    expected=[dict(e.payload,timestamp_ms=replay.epoch+e.at) for e in schedule.events if e.stream==i]
                    assert actual==expected,(i,len(actual),len(expected))
                    assert not server.errors,server.errors
                print('PASS: real Liminal binary received, parsed and forwarded all 36 machine + 2644 sensor payloads unchanged over framed TCP.')
    finally:
        if manager is not None:manager.close()
        if process is not None and process.poll() is None:
            process.terminate()
            try:process.wait(5)
            except subprocess.TimeoutExpired:process.kill();process.wait(5)
        for sock in reservations:sock.close()
        for server in outputs:server.close()


if __name__=='__main__':
    main()
