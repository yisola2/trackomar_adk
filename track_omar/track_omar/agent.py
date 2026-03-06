from datetime import datetime, timedelta
from google.adk.agents import LlmAgent, SequentialAgent, LoopAgent
from google.adk.tools.agent_tool import AgentTool
from track_omar.callbacks import verifier_avant_sauvegarde, maj_streak_apres_outil, ignorer_budget_si_revenus_seuls
from track_omar.tools.my_tools import (
    sauvegarder_toutes_transactions,
    verifier_categorie_suivante,
    obtenir_categorie_courante,
    obtenir_budget_resultat,
    calculer_solde_budget,
    lire_contexte_alertes,
    enregistrer_alerte,
    envoyer_notif,
)


def get_date_context() -> str:
    today = datetime.now()
    yesterday = today - timedelta(days=1)
    tomorrow = today + timedelta(days=1)
    day_names = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
    last_monday = today - timedelta(days=today.weekday() + 7)
    last_week_days = {
        day_names[i]: (last_monday + timedelta(days=i)).strftime("%Y-%m-%d")
        for i in range(7)
    }
    last_week_str = "\n    ".join([f"{k} dernier : {v}" for k, v in last_week_days.items()])
    return f"""
    Contexte temporel :
    Aujourd'hui : {today.strftime("%Y-%m-%d")} ({day_names[today.weekday()]})
    Hier : {yesterday.strftime("%Y-%m-%d")}
    Demain : {tomorrow.strftime("%Y-%m-%d")}
    {last_week_str}
    """


# ─── Agent 1 : Transcription ───────────────────────────────────────────────
transcription_agent = LlmAgent(
    name="TranscriptionAgent",
    model="gemini-2.5-flash",
    instruction="""
    Tu reçois un texte brut issu d'une transcription vocale.
    Nettoie et reformule ce texte pour le rendre clair et exploitable.
    Retourne uniquement le texte nettoyé, sans commentaire.
    """,
    output_key="texte_nettoye"
)


# ─── Agent 2 : Extraction ──────────────────────────────────────────────────
extraction_agent = LlmAgent(
    name="ExtractionAgent",
    model="gemini-2.5-flash",
    instruction=f"""
    {get_date_context()}

    Tu reçois ce texte : {{texte_nettoye}}

    Extrais TOUTES les transactions et retourne UNIQUEMENT un tableau JSON valide (sans backticks).
    Chaque objet doit avoir : montant (float), type ("depense"/"revenu"),
    categorie (depense: resto/transport/courses/loisirs/sante/loyer/autre,
               revenu: salaire/remboursement/virement/autre),
    date (YYYY-MM-DD), description (string).

    Exemple de sortie attendue :
    [{{"montant": 12.0, "type": "depense", "categorie": "resto", "date": "{datetime.now().strftime('%Y-%m-%d')}", "description": "kebab"}}, {{"montant": 3.0, "type": "depense", "categorie": "transport", "date": "{datetime.now().strftime('%Y-%m-%d')}", "description": "metro"}}]
    """,
    output_key="transactions_json"
)


# ─── Agent 3 : Sauvegarde (1 seul appel outil, Python fait le reste) ──────
sauvegarde_agent = LlmAgent(
    name="SauvegardeAgent",
    model="gemini-2.5-flash",
    instruction="""
    Appelle sauvegarder_toutes_transactions (sans argument).
    Réponds avec le résumé retourné par l'outil.
    """,
    tools=[sauvegarder_toutes_transactions],
    output_key="resultat_sauvegarde",
    before_agent_callback=verifier_avant_sauvegarde,
    after_tool_callback=maj_streak_apres_outil,
)


# ─── Agent 4 : Budget (utilisé comme AgentTool) ────────────────────────────
budget_agent = LlmAgent(
    name="BudgetAgent",
    model="gemini-2.5-flash",
    instruction="""
    Tu reçois une catégorie de dépense.
    Appelle calculer_solde_budget avec cette catégorie.
    Retourne UNIQUEMENT le JSON brut retourné par l'outil, sans reformuler.
    """,
    tools=[calculer_solde_budget],
)


# ─── Agent 5 : Alertes ─────────────────────────────────────────────────────
alert_agent = LlmAgent(
    name="AlertAgent",
    model="gemini-2.5-flash",
    instruction="""
    Tu es un agent de notification budget taquin et bienveillant.

    1. Appelle obtenir_categorie_courante pour savoir quelle catégorie est concernée.
    2. Appelle calculer_solde_budget avec cette catégorie pour avoir le pourcentage consommé.
    3. Appelle lire_contexte_alertes avec la catégorie obtenue.
    4. Génère un message personnalisé selon le contexte retourné :
       - "premiere_fois" → mise en garde légère et taquine
       - "deuxieme_fois" → plus sérieux mais bienveillant
       - "recidive" → ferme mais encourageant
       - Si streak_jours > 7 → mentionne la streak perdue
    5. Appelle envoyer_notif avec le message généré.
    6. Appelle enregistrer_alerte avec la catégorie.
    """,
    tools=[obtenir_categorie_courante, calculer_solde_budget, lire_contexte_alertes, envoyer_notif, enregistrer_alerte],
)


# ─── Agent 6 : Orchestrateur budget ────────────────────────────────────────
orchestrateur_agent = LlmAgent(
    name="OrchestratorAgent",
    model="gemini-2.5-flash",
    instruction="""
    1. Appelle verifier_categorie_suivante (sans argument).
    2. Si "termine" est true : réponds "Toutes catégories vérifiées."
    3. Sinon, note la catégorie retournée et appelle BudgetAgent avec cette catégorie.
    4. Si le résultat de BudgetAgent indique alerte=True : transfère le contrôle à AlertAgent.
    5. Sinon : réponds "OK, budget non dépassé pour cette catégorie."
    """,
    tools=[verifier_categorie_suivante, AgentTool(agent=budget_agent)],
    sub_agents=[alert_agent],
)


# ─── Agent 7 : Résumé final ────────────────────────────────────────────────
resume_agent = LlmAgent(
    name="ResumeAgent",
    model="gemini-2.5-flash",
    instruction="""
    Le texte traité était : {texte_nettoye}
    Les transactions sauvegardées : {resultat_sauvegarde}

    Génère un court résumé en français de ce qui a été enregistré (1-2 phrases max).
    """
)


# ─── Workflow ────────────────────────────────────────────────────────────────

# LoopAgent : vérifie le budget pour chaque catégorie de dépense
budget_loop = LoopAgent(
    name="BudgetLoop",
    max_iterations=10,
    sub_agents=[orchestrateur_agent],
    before_agent_callback=ignorer_budget_si_revenus_seuls,
)

# Agent racine
root_agent = SequentialAgent(
    name="RootAgent",
    sub_agents=[
        transcription_agent,   # nettoie le texte
        extraction_agent,      # extrait toutes les transactions → transactions_json
        sauvegarde_agent,      # sauvegarde tout en Python → categories_a_verifier
        budget_loop,           # vérifie budget par catégorie (LoopAgent)
        resume_agent,          # résumé final affiché à l'utilisateur
    ]
)
