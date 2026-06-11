' Mồi lửa ẩn cho Task Scheduler — chạy run_local_pipeline.ps1 không hiện cửa sổ.
' Tham số cuối True = ĐỨNG CHỜ pipeline xong mới thoát, để Task Scheduler thấy task
' còn sống → IgnoreNew chặn được chồng lặp giữa các tick 1 phút.
CreateObject("Wscript.Shell").Run "powershell.exe -NoProfile -ExecutionPolicy Bypass -File ""c:\Tool\crypto-sentinel\scripts\run_local_pipeline.ps1""", 0, True
