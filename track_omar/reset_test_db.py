"""
Remet la base SQLite dans un état connu avant de lancer les evals.
Lance depuis agentic_ai/track_omar/ :
    python reset_test_db.py
"""

import sqlite3
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), "track_omar", "tools", "trackomar.db")
MONTH_START = datetime.now().strftime("%Y-%m-01")


def reset():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Vider toutes les transactions du mois courant
    cursor.execute("DELETE FROM transactions WHERE date >= ?", (MONTH_START,))
    deleted = cursor.rowcount
    print(f"[reset] {deleted} transaction(s) du mois supprimee(s)")

    # S'assurer que les budgets de test sont en place
    budgets = [
        ("resto",      50),
        ("transport",  50),
        ("courses",   200),
        ("loisirs",   150),
        ("loyer",     700),
        ("sante",     100),
        ("autre",     200),
    ]
    for categorie, limite in budgets:
        cursor.execute(
            "INSERT INTO budgets (categorie, limite) VALUES (?, ?) "
            "ON CONFLICT(categorie) DO UPDATE SET limite = excluded.limite",
            (categorie, limite)
        )
    print(f"[reset] {len(budgets)} budget(s) verifies/mis a jour")

    conn.commit()
    conn.close()
    print("[reset] DB prete pour les evals")


if __name__ == "__main__":
    reset()
