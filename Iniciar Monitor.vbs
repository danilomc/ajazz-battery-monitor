Set WshShell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
strPath = fso.GetParentFolderName(WScript.ScriptFullName)

Dim pythonw
If fso.FileExists("C:\Python315\pythonw.exe") Then
    pythonw = "C:\Python315\pythonw.exe"
Else
    pythonw = "pythonw.exe"
End If

Dim script
script = strPath & "\ajazz_battery.pyw"

WshShell.CurrentDirectory = strPath
WshShell.Run Chr(34) & pythonw & Chr(34) & " " & Chr(34) & script & Chr(34), 0, False
