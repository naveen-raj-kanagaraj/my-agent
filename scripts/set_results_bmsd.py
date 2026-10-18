"""Enter the BMSD 2026 Grand Finals results into Predict & Win and show the winners on /predict.

    cd ~/my-agent && venv/bin/python scripts/set_results_bmsd.py

Safe to run while the agent is running (runs on the Mac, same database). Run it again any time; it overwrites.
Typed answers: every spelling of the right player counts, including obvious misspellings; answers naming
two or more players do not.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import predict  # noqa: E402

TEAMS = {
    "CHAMPION": "Soul",
    "TOP 3": ["Soul", "8Bit Esports", "Gladiators"],
    "BMIC": ["Soul", "Gladiators", "8Bit Esports", "K9 Esports", "Blitz x Epigrotive", "Outrage"],
    "PEAK VIEWERS": "600K-700K",
}
TEXT = {   # accepted spellings, from what players actually typed
    "FINAL MVP": ["IQ00SoulLeGiT", "IQOOSOULxLegit", "IQOOSoulLegit", "IQOOsoulLegit", "IqooSoulLegit", "IqooSoullegit", "Iqoosoul legit", "IqoosoulLegit", "Iqoosoullegit", "Iqooxsoullegit", "LEGIT", "Legit", "Legitt", "Ligit", "SouL Legit", "Soul Legit", "Soul legit", "SoulLegit", "Soullegit", "iQOOSouLLegit", "legit"],            # Legit
    "TOURNAMENT MVP": ["IQOO8BITSUBH1", "Shub", "Shubh", "Subh"],       # Shubh
    "BEST IGL": ["AAreeb", "AREEB", "Aarib", "Aree.", "Areeb", "Areeeb", "Arib", "Aribe", "Arreb", "BLITZ AREEB", "BLTZAREEB", "Blitz Areeb", "Blitz aareb", "Blitz areeb", "BlitzEGAreeb28", "EGxAREEB", "EGxAreeb", "areeb"],             # Areeb
    "THE ELIMINATOR": ["K9 TAURUS", "K9 Tauras", "K9 Taurus", "K9 tarsur", "K9 tarus", "K9 taurus", "K9 toras", "K9 tourse", "K9TAURUS", "K9Tarus", "K9Tauras", "K9Taurus", "K9tarus", "K9tauras", "K9taurus", "K9touras", "K9x taurus", "K9xTauras", "K9xTaurus", "K9xTauruss", "K9xTouras", "K9\u00d7tauras", "KoTaurus", "TAURAS", "TAURUS", "Taraus", "Tarous", "Tarus", "Tauras", "Tauras (K9)", "Taurash", "Taurass", "Tauraus", "Taurus", "Taurus06", "Taurush", "Taurusog", "Tauruss", "Tautas", "Tharus", "Toras", "Torus", "Touras", "Tours", "k9 taurus", "tarus", "tauras", "taurus"],       # Taurus
}

for q in predict.questions():
    v = TEAMS.get(q["tag"], TEXT.get(q["tag"]))
    if v is not None:
        predict.update_question(q["id"], "answer", v)
        print(f"{q['tag']}: set")
predict.save_settings(show_leaderboard=True, peak_actual="653K", podium=["Soul", "8Bit Esports", "Gladiators"])
players, sc, _, _ = predict._scores()
for r in predict._ranked(players, sc, "all")[:5]:
    print(f"#{r['rank']} @{r['handle']} {r['pts']} pts")
print("Done. /predict shows the winners within a minute.")
