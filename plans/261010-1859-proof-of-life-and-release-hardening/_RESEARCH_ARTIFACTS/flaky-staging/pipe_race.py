"""Fire SIGTERM at a bash running pipe-race.sh at a random 0-30 ms offset after it starts; report any
process still alive 4 s later (a hang). usage: pipe_race.py BASH N"""
import os, random, signal, subprocess, sys, time
bash, n = sys.argv[1], int(sys.argv[2])
script = sys.argv[3] if len(sys.argv) > 3 else "pipe-race.sh"   # usage: pipe_race.py BASH N [SCRIPT]
here = os.path.dirname(os.path.abspath(__file__))
hung = 0
for i in range(n):
    p = subprocess.Popen([bash, os.path.join(here, script)], stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)
    time.sleep(random.uniform(0.0, 0.03))
    p.send_signal(signal.SIGTERM)
    try:
        p.wait(timeout=4)
    except subprocess.TimeoutExpired:
        hung += 1
        print(i, "HANG", subprocess.run(["ps", "-o", "pid,ppid,stat,command", "-g", str(p.pid)],
                                        capture_output=True, text=True).stdout)
        os.killpg(p.pid, signal.SIGKILL); p.wait()
print(bash, "hung", hung, "of", n)
