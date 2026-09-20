import subprocess
import time
import MetaTrader5 as mt5

print("Step 1: Launching terminal64.exe...")
p = subprocess.Popen([r"C:\Program Files\MetaTrader 5\terminal64.exe"])
print(f"Launched PID {p.pid}. Waiting 4 seconds for UI to initialize...")
time.sleep(4)

print("Step 2: Attaching via mt5.initialize()...")
res = mt5.initialize()
print("Attach result:", res, mt5.last_error())
if res:
    print("Terminal info:", mt5.terminal_info())
    print("Current account:", mt5.account_info())
    
    print("\nStep 3: Trying mt5.login() with FundedSquad-Server...")
    log_res = mt5.login(login=134289849, password="1wkYO95PT", server="FundedSquad-Server")
    print("Login result:", log_res, mt5.last_error())
    if log_res:
        print("Logged in account:", mt5.account_info())
    mt5.shutdown()
