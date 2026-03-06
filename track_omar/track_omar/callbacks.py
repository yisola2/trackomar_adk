from datetime import datetime
from typing import Optional

from google.adk.agents.callback_context import CallbackContext
from google.adk.tools.base_tool import BaseTool
from google.adk.tools.tool_context import ToolContext
from google.genai import types


def verifier_avant_sauvegarde(callback_context: CallbackContext) -> Optional[types.Content]:
    """
    before_agent_callback sur SauvegardeAgent.

    Vérifie que le JSON des transactions est présent dans le state avant de lancer l'agent.
    Si absent, court-circuite l'agent et retourne un message d'erreur directement.
    """
    state = callback_context.state
    transactions_json = state.get("transactions_json", "")

    print(f"\n[CALLBACK before_agent] SauvegardeAgent — {datetime.now().strftime('%H:%M:%S')}")

    if not transactions_json or transactions_json.strip() in ("", "[]", "null"):
        print("[CALLBACK] Aucun JSON de transactions trouvé → agent court-circuité")
        callback_context.state["resultat_sauvegarde"] = "Aucune transaction à sauvegarder."
        return types.Content(
            role="model",
            parts=[types.Part(text="Aucune transaction à sauvegarder.")]
        )

    print(f"[CALLBACK] transactions_json présent ({len(transactions_json)} caractères) → agent lancé")
    return None  # Laisser l'agent tourner normalement


def ignorer_budget_si_revenus_seuls(callback_context: CallbackContext) -> Optional[types.Content]:
    """
    before_agent_callback sur BudgetLoop.

    Si categories_a_verifier est vide (que des revenus), court-circuite le LoopAgent
    pour éviter un tour à vide inutile.
    """
    categories = callback_context.state.get("categories_a_verifier", [])

    print(f"\n[CALLBACK before_agent] BudgetLoop — {datetime.now().strftime('%H:%M:%S')}")

    if not categories:
        print("[CALLBACK] Aucune dépense à vérifier (revenus uniquement) → BudgetLoop ignoré")
        return types.Content(
            role="model",
            parts=[types.Part(text="Aucune dépense à vérifier.")]
        )

    print(f"[CALLBACK] {len(categories)} catégorie(s) à vérifier : {categories}")
    return None


def maj_streak_apres_outil(
    tool: BaseTool,
    args: dict,
    tool_context: ToolContext,
    tool_response: dict
) -> Optional[dict]:
    """
    after_tool_callback sur SauvegardeAgent.

    Après sauvegarder_toutes_transactions : incrémente le streak quotidien
    (nombre de jours sans dépassement de budget).
    Ce compteur sera utilisé par AlertAgent pour personnaliser les messages.
    """
    if tool.name != "sauvegarder_toutes_transactions":
        return None

    nb = tool_response.get("nb_sauvegardees", 0)
    if nb > 0:
        streak = tool_context.state.get("streak_sans_depassement", 0)
        tool_context.state["streak_sans_depassement"] = streak + 1
        print(f"[CALLBACK after_tool] {nb} transaction(s) sauvegardée(s) → streak: {streak + 1} jours")

    return None  # Ne pas modifier la réponse de l'outil
