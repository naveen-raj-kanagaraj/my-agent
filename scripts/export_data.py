"""Write the analysis files now (the tracker also does this every 10 minutes while it runs).

Usage, from ~/my-agent:  python3 scripts/export_data.py [event_key]      (default: bmsd)
Output: exports/<event>/ (viewership every 2 min, streams every 2 min, daily peaks, xlsx),
        exports/predict/questions.csv, exports/private/ (players and picks; never pushed to GitHub).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import dataexport  # noqa: E402

key = sys.argv[1] if len(sys.argv) > 1 else "bmsd"
print(dataexport.viewership(key))
if key == "bmsd":
    print(dataexport.predict_data())
