"""Create Predict & Win questions from a config file (same as the admin page buttons).

Usage (on the Mac, from ~/my-agent):
  python scripts/predict_setup.py config/predict_bmsd2026.json            # settings + tournament + Day 1
  python scripts/predict_setup.py config/predict_bmsd2026.json --day 2    # add Day 2 questions
Safe to run twice: nothing is duplicated.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import predict  # noqa: E402


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return
    cfg = json.load(open(sys.argv[1]))
    day = int(sys.argv[sys.argv.index("--day") + 1]) if "--day" in sys.argv else 1
    predict.save_settings(**cfg["settings"])
    made = predict.create_event_set() if day == 1 else []
    made += predict.create_day_set(day)
    print(f"Created {len(made)} questions. Total now: {len(predict.questions())}")
    for q in predict.questions():
        print(f"  #{q['id']:<3} day {q['day'] or '-'}  {predict.fmt_ist(q['close_ts'])}  {q['title']}")


if __name__ == "__main__":
    main()
