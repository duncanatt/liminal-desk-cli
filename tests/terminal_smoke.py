"""Drive the actual Textual UI against the isolated MQTT protocol test server."""
import argparse, tempfile, signal
import os, pty, fcntl, termios, struct, subprocess, select, time, sys
from pathlib import Path
from tests.test_mqtt_integration import LoopbackMqtt
from tests.test_tcp_integration import FrameServer

root=Path(__file__).resolve().parent.parent
parser=argparse.ArgumentParser()
parser.add_argument('--transport',choices=('mqtt','tcp'),default='mqtt')
options=parser.parse_args()
server=FrameServer() if options.transport=='tcp' else LoopbackMqtt()
master,slave=pty.openpty()
fcntl.ioctl(slave,termios.TIOCSWINSZ,struct.pack('HHHH',36,140,0,0))
env=dict(os.environ,TERM='xterm-256color',PYTHONDONTWRITEBYTECODE='1')
process=subprocess.Popen([sys.executable,'-B','-m','liminal_desk_cli','--transport',options.transport,'--host','127.0.0.1','--port',str(server.port)],cwd=root,stdin=slave,stdout=slave,stderr=slave,env=env,start_new_session=True)
os.close(slave);output=bytearray()
def pump(seconds=.15):
 deadline=time.monotonic()+seconds
 while time.monotonic()<deadline:
  if select.select([master],[],[],.02)[0]:
   try:output.extend(os.read(master,65536))
   except OSError:break
def key(value):os.write(master,value.encode());pump()
def wait(condition,seconds=6):
 deadline=time.monotonic()+seconds
 while time.monotonic()<deadline:
  pump(.03)
  if condition():return
 raise AssertionError('UI condition timed out; tail: '+output[-2500:].decode(errors='replace'))
try:
 pump(1);key('c');wait(lambda:(b'Connected (local write' if options.transport=='tcp' else b'subscriptions active') in output)
 key('d');key('n');wait(lambda:len(server.messages)==6)
 key('n');wait(lambda:len(server.messages)==48)
 pump(.3)
 # Navigate to the last event, inspect its payload, then return to the table.
 key('e');key('\x1b[1;5F');key('\r');pump(.2)
 assert (b'Broker acknowledged' if options.transport=='mqtt' else b'TCP written locally') in output,'Payload inspector not rendered'
 key('\x1b');key('v')
 key('r');key('a');wait(lambda:len(server.messages)>=58)
 key('p');pump(.2);count=len(server.messages);pump(.3)
 assert len(server.messages)==count,'Messages continue during pause'
 key('p');wait(lambda:len(server.messages)>count)
 key('q');process.wait(5)
 assert process.returncode==0,process.returncode
 assert b"is not defined" not in output
 assert not server.errors,server.errors
 (Path(tempfile.gettempdir())/('liminal-ui-'+options.transport+'-transcript.txt')).write_bytes(output)
 print('PASS: real module launch, transport connect/receive, two N batches, scroll and payload inspector, previous batch, reset, automatic replay, pause/resume and clean quit.')
finally:
 (Path(tempfile.gettempdir())/('liminal-ui-'+options.transport+'-transcript.txt')).write_bytes(output)
 if process.poll() is None:
  process.terminate()
  try:process.wait(3)
  except subprocess.TimeoutExpired:process.kill();process.wait(3)
 os.close(master);server.close()
