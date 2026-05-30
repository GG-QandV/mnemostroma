#!/usr/bin/env python3
import os
import sys
import pty
import select

def main():
    password = "1801".encode("utf-8")
    
    # We want to run: scp -o StrictHostKeyChecking=no /tmp/mnemostroma.zip Capricorn@192.168.1.243:C:/Users/Capricorn/Downloads/mnemostroma.zip
    scp_args = ["scp", "-o", "StrictHostKeyChecking=no", "/tmp/mnemostroma.zip", "Capricorn@192.168.1.243:C:/Users/Capricorn/Downloads/mnemostroma.zip"]
    
    pid, fd = pty.fork()
    if pid == 0:
        os.execvp("scp", scp_args)
    else:
        password_sent = False
        while True:
            r, w, x = select.select([fd], [], [], 30)
            if not r:
                break
            try:
                data = os.read(fd, 4096)
            except OSError:
                break
            if not data:
                break
            sys.stdout.buffer.write(data)
            sys.stdout.buffer.flush()
            
            if b"password:" in data.lower() and not password_sent:
                os.write(fd, password + b"\n")
                password_sent = True
                
        try:
            os.waitpid(pid, 0)
        except OSError:
            pass

if __name__ == "__main__":
    main()
