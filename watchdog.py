# watchdog.py
import subprocess
import time

RYU_SESSION = "ryu"
MN_SESSION  = "mininet"


def cleanup_tmux():
    subprocess.run(["sudo", "tmux", "kill-session", "-t", RYU_SESSION],
                   capture_output=True)
    subprocess.run(["sudo", "tmux", "kill-session", "-t", MN_SESSION],
                   capture_output=True)
def new_tmux(session, cmd):
    subprocess.Popen([
        "gnome-terminal", "--",
        "bash", "-c",
        f"tmux new-session -s {session} '{cmd}'; exec bash"
    ])

def tmux_send(session, cmd):
    subprocess.run(["tmux", "send-keys", "-t", session, cmd, "Enter"])

if __name__ == "__main__":
    cleanup_tmux()
    
    print("[watchdog] 啟動 Ryu...")
    new_tmux(RYU_SESSION, "ryu-manager DTM.py --observe-links")
    time.sleep(3)

    print("[watchdog] 啟動 Mininet...")
    new_tmux(MN_SESSION, "sudo python new_topo.py")

    print("[watchdog] 等待 10 秒...")
    time.sleep(10)

    print("[watchdog] 送出 sendarp")
    tmux_send(MN_SESSION, "sendarp")
    
    time.sleep(10)