Dim fso, shell, here, target, link
Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")

here = fso.GetParentFolderName(WScript.ScriptFullName)
target = here & "\run_hidden.vbs"

Set link = shell.CreateShortcut(shell.SpecialFolders("Startup") & "\MoneyBot.lnk")
link.TargetPath = target
link.WorkingDirectory = here
link.WindowStyle = 7
link.Description = "Telegram bot: expenses and income"
link.Save

' Start it right away, without waiting for the next logon.
shell.Run "cmd /c """ & here & "\run_silent.bat""", 0, False

MsgBox "Autostart installed." & vbCrLf & vbCrLf & _
       "The bot is starting in background and will start at every logon." & vbCrLf & _
       "Log file: " & here & "\logs\bot.log" & vbCrLf & vbCrLf & _
       "Stop it with stop_bot.bat", 64, "MoneyBot"
