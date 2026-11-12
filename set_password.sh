#!/bin/bash
# Saves the Google App Password into config.env. The password is not shown while you paste it.
cd "$(dirname "$0")"
read -r -s -p "Paste your 16-letter App Password, then press Return: " PW
echo
PW="${PW// /}"   # Google shows it with spaces; remove them
if [ ${#PW} -lt 16 ]; then
  echo "That looks too short (got ${#PW} characters). Nothing was saved. Please try again."
  exit 1
fi
python3 - "$PW" <<'EOF'
import sys, re, pathlib
p = pathlib.Path("config.env")
s = p.read_text()
s = re.sub(r"(?m)^SMTP_PASSWORD=.*$", lambda m: "SMTP_PASSWORD=" + sys.argv[1], s)
p.write_text(s)
EOF
chmod 600 config.env
echo "Saved. You can go back to Claude now."
