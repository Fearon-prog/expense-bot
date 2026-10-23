Dim fso, shell, linkPath
Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")

linkPath = shell.SpecialFolders("Startup") & "\MoneyBot.lnk"

If fso.FileExists(linkPath) Then
    fso.DeleteFile linkPath, True
    MsgBox "Autostart removed." & vbCrLf & vbCrLf & _
           "The bot keeps running now. Stop it with stop_bot.bat.", 64, "MoneyBot"
Else
    MsgBox "Autostart was not installed.", 48, "MoneyBot"
End If
