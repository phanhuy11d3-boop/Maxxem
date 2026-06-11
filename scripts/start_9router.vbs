' Khởi động 9Router ẩn (tray mode, không mở browser) — dùng cho task logon.
' False = không chờ (9Router là daemon chạy mãi).
CreateObject("Wscript.Shell").Run "cmd /c 9router -n -t --skip-update", 0, False
