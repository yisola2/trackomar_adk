import sqlite3
import json
from datetime import datetime
import os
from google.adk.tools.tool_context import ToolContext

DB_PATH = os.path.join(os.path.dirname(__file__), "trackomar.db")


def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            montant REAL NOT NULL,
            categorie TEXT NOT NULL,
            date TEXT NOT NULL,
            description TEXT,
            type TEXT NOT NULL DEFAULT 'depense',
            created_at TEXT
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS budgets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            categorie TEXT UNIQUE NOT NULL,
            limite REAL NOT NULL
        )
    """)
    conn.commit()
    conn.close()

init_db()


def sauvegarder_toutes_transactions(tool_context: ToolContext) -> dict:
    """
    Lit le JSON des transactions depuis le state, les sauvegarde toutes en base,
    et prépare la liste des catégories de dépenses à vérifier pour le budget.

    Returns:
        dict avec le nombre de transactions sauvegardées et un résumé
    """
    categories_valides_depense = ["resto", "transport", "courses", "loisirs", "sante", "loyer", "autre"]
    categories_valides_revenu = ["salaire", "remboursement", "virement", "autre"]

    raw = tool_context.state.get("transactions_json", "[]")
    # Nettoyer les backticks markdown
    raw = raw.strip()
    if raw.startswith("```"):
        lines = raw.split("\n")
        raw = "\n".join(lines[1:-1]) if len(lines) > 2 else raw
    raw = raw.strip()

    try:
        data = json.loads(raw)
        if isinstance(data, dict) and "transactions" in data:
            transactions = data["transactions"]
        elif isinstance(data, list):
            transactions = data
        elif isinstance(data, dict):
            transactions = [data]
        else:
            transactions = []
    except Exception as e:
        return {"erreur": f"Impossible de parser le JSON: {e}", "raw": raw[:200]}

    if not transactions:
        return {"erreur": "Aucune transaction trouvée dans le JSON"}

    saved = []
    categories_depense = []
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    for tx in transactions:
        try:
            montant = float(tx.get("montant", 0))
            categorie = str(tx.get("categorie", "autre")).lower()
            type_tx = str(tx.get("type", "depense")).lower()
            description = str(tx.get("description", ""))
            date = str(tx.get("date", datetime.now().strftime("%Y-%m-%d")))

            if montant <= 0 or montant > 100000:
                continue

            if type_tx == "revenu" and categorie not in categories_valides_revenu:
                categorie = "autre"
            elif type_tx == "depense" and categorie not in categories_valides_depense:
                categorie = "autre"

            cursor.execute(
                "INSERT INTO transactions (montant, categorie, date, description, type, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (montant, categorie, date, description, type_tx, now)
            )
            saved.append({"montant": montant, "categorie": categorie, "type": type_tx})

            if type_tx == "depense" and categorie not in categories_depense:
                categories_depense.append(categorie)

        except Exception as e:
            continue

    conn.commit()
    conn.close()

    # Stocker les catégories à vérifier pour le LoopAgent budget
    tool_context.state["categories_a_verifier"] = categories_depense
    tool_context.state["transactions_sauvegardees"] = saved

    return {
        "nb_sauvegardees": len(saved),
        "transactions": saved,
        "categories_a_verifier_budget": categories_depense
    }


def verifier_categorie_suivante(tool_context: ToolContext) -> dict:
    """
    Récupère la prochaine catégorie à vérifier pour le budget.
    Déclenche l'escalade du LoopAgent quand toutes les catégories ont été vérifiées.

    Returns:
        dict avec 'termine': True si fini, sinon 'categorie': str
    """
    categories = tool_context.state.get("categories_a_verifier", [])

    if not categories:
        tool_context.actions.escalate = True
        return {"termine": True}

    categorie = categories[0]
    tool_context.state["categories_a_verifier"] = categories[1:]
    tool_context.state["categorie_courante"] = categorie
    return {"termine": False, "categorie": categorie}


def calculer_solde_budget(categorie: str, tool_context: ToolContext) -> dict:
    """
    Calcule le pourcentage du budget mensuel consommé pour une catégorie.

    Args:
        categorie: La catégorie de dépense (ex: 'resto', 'transport')

    Returns:
        dict avec pourcentage consommé, limite, total dépensé ce mois
    """
    month_start = datetime.now().strftime("%Y-%m-01")

    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT COALESCE(SUM(montant), 0) FROM transactions
            WHERE categorie = ? AND type = 'depense' AND date >= ?
        """, (categorie.lower(), month_start))
        total_depense = cursor.fetchone()[0]

        cursor.execute("SELECT limite FROM budgets WHERE categorie = ?", (categorie.lower(),))
        budget_row = cursor.fetchone()
        conn.close()

        if not budget_row:
            return {
                "categorie": categorie,
                "budget_defini": False,
                "total_depense": total_depense,
            }

        limite = budget_row[0]
        pourcentage = round((total_depense / limite * 100) if limite > 0 else 0, 1)

        return {
            "categorie": categorie,
            "budget_defini": True,
            "limite": limite,
            "total_depense": total_depense,
            "pourcentage": pourcentage,
            "alerte": pourcentage >= 80
        }
    except Exception as e:
        return {"erreur": str(e)}


def lire_contexte_alertes(categorie: str, tool_context: ToolContext) -> dict:
    """
    Lit l'historique des alertes budget pour personnaliser le message.

    Args:
        categorie: La catégorie concernée

    Returns:
        dict avec nb alertes ce mois, streak, contexte
    """
    historique = tool_context.state.get("historique_alertes", {})
    streak = tool_context.state.get("streak_sans_depassement", 0)
    budget_precedent = tool_context.state.get("budget_mois_precedent", {})

    nb_alertes = historique.get(categorie, 0)

    return {
        "nb_alertes_ce_mois": nb_alertes,
        "streak_jours": streak,
        "pourcentage_mois_precedent": budget_precedent.get(categorie, None),
        "contexte": (
            "premiere_fois" if nb_alertes == 0
            else "recidive" if nb_alertes >= 2
            else "deuxieme_fois"
        )
    }


def enregistrer_alerte(categorie: str, tool_context: ToolContext) -> dict:
    """
    Enregistre qu'une alerte a été envoyée. Remet le streak à 0.

    Args:
        categorie: La catégorie concernée
    """
    historique = tool_context.state.get("historique_alertes", {})
    historique[categorie] = historique.get(categorie, 0) + 1
    tool_context.state["historique_alertes"] = historique
    tool_context.state["streak_sans_depassement"] = 0
    return {"enregistre": True, "nb_total_alertes": historique[categorie]}


def obtenir_categorie_courante(tool_context: ToolContext) -> dict:
    """
    Retourne la catégorie en cours de vérification budget depuis le state.

    Returns:
        dict avec 'categorie': str ou 'aucune': True si non définie
    """
    cat = tool_context.state.get("categorie_courante", None)
    if cat:
        return {"categorie": cat}
    return {"aucune": True}


def obtenir_budget_resultat(tool_context: ToolContext) -> dict:
    """
    Retourne le dernier résultat de vérification budget depuis le state.

    Returns:
        dict avec les infos budget ou dict vide
    """
    import json as _json
    raw = tool_context.state.get("budget_resultat", "{}")
    if isinstance(raw, dict):
        return raw
    try:
        return _json.loads(raw)
    except Exception:
        return {}


def envoyer_notif(message: str) -> dict:
    """
    Envoie une notification à l'utilisateur.

    Args:
        message: Le message personnalisé à envoyer
    """
    print(f"\n{'='*50}\nALERTE BUDGET : {message}\n{'='*50}\n")
    return {"envoye": True, "message": message}
