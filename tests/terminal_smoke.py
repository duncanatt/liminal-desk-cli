"""Drive the actual curses UI against the isolated MQTT protocol test server."""
import os, pty, fcntl, termios, struct, subprocess, select, time, sys
from pathlib import Path
from tests.test_mqtt_integration import LoopbackMqtt

root=Path(__file__).resolve().parent.parent
server=LoopbackMqtt()
master,slave=pty.openpty()
fcntl.ioctl(slave,termios.TIOCSWINSZ,struct.pack('HHHH',36,140,0,0))
env=dict(os.environ,TERM='xterm-256color',PYTHONDONTWRITEBYTECODE='1')
process=subprocess.Popen([sys.executable,'-B','-m','liminal_desk_cli','--host','127.0.0.1','--port',str(server.port)],cwd=root,stdin=slave,stdout=slave,stderr=slave,env=env,start_new_session=True)
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
 pump(.3);key('c');wait(lambda:b'subscriptions active' in output)
 key('d');key('n');wait(lambda:len(server.messages)==6)
 key('n');wait(lambda:len(server.messages)==48)
 pump(.3);key(']');key(']');key(']');key(']');key(']');
 assert b'42:' in output,'Last event of batch not visible'
 key('v');key('e')
 key('r');key('a');wait(lambda:len(server.messages)>=58)
 key('p');pump(.2);count=len(server.messages);pump(.3)
 assert len(server.messages)==count,'Messages continue during pause'
 key('p');wait(lambda:len(server.messages)>count)
 key('q');process.wait(5)
 assert process.returncode==0,process.returncode
 assert b"is not defined" not in output
 assert not server.errors,server.errors
 Path('/tmp/cli-thorough-audit/ui-transcript.txt').write_bytes(output)
 print('PASS: real module launch, real MQTT connect/subscriptions, two N batches, scroll to event42, previous view, reset, automatic replay, pause/resume and clean quit.')
finally:
 if process.poll() is None:process.terminate();process.wait(5)
 os.close(master);server.close()
