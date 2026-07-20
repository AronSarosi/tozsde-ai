# Tozsde AI - daily pipeline runner
# Scheduled task runs this on weekdays after US market close (22:15 Budapest time).
# Manual run: powershell -NoProfile -ExecutionPolicy Bypass -File daily_run.ps1
Set-Location "C:\Users\arons\Documents\Tozsde-AI"
$stamp = Get-Date -Format "yyyy-MM-dd HH:mm"
"[$stamp] daily run start" | Out-File -FilePath "data\daily_run.log" -Append -Encoding utf8
python -X utf8 pipeline.py daily 2>&1 | Out-File -FilePath "data\daily_run.log" -Append -Encoding utf8

# Publish fresh snapshots to the deployed (Vercel) site.
git add snapshot
git diff --cached --quiet
if ($LASTEXITCODE -ne 0) {
    git commit -m "Daily snapshot $(Get-Date -Format yyyy-MM-dd)"
    git push
    "[$stamp] snapshot pushed" | Out-File -FilePath "data\daily_run.log" -Append -Encoding utf8
}
