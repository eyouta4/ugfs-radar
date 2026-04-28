"""
scripts/recalibrate_weights.py — Boucle d'apprentissage continue.

Lit toutes les opportunités avec une décision client (GO / NO_GO),
extrait leurs sous-scores du `score_breakdown` (déjà persisté), entraîne
une régression logistique, et sauvegarde les nouveaux poids comme version
active dans la table `scoring_weights`.

Recalibration cadencée :
  - Trigger automatique : si nb feedbacks acquis depuis dernière calibration ≥ 5
                           (paramétré dans ugfs_profile.yaml learning.min_feedbacks_for_recalibration)
  - Trigger manuel : exécution directe de ce script

Méthode : LogisticRegression(L2) avec normalisation des poids pour
sommer à 100 (préservation de l'interprétabilité du score 0-100).

Si pas assez de données, on log un warning et on conserve les poids actuels.
"""
from __future__ import annotations

import asyncio

import numpy as np
from sklearn.linear_model import LogisticRegression
from sqlalchemy import select

from src.config.logger import get_logger
from src.config.settings import get_ugfs_profile
from src.storage.database import init_db, session_scope
from src.storage.models import Opportunity
from src.storage.repository import WeightsRepo

logger = get_logger(__name__)


CRITERIA = [
    "geography_match",
    "theme_match",
    "vehicle_match",
    "partner_match",
    "deadline_feasibility",
    "ticket_in_sweet_spot",
    "language_match",
    "similarity_to_past_go",
]


async def main():
    profile = get_ugfs_profile()
    learning_cfg = profile.get("learning", {})
    min_feedbacks = learning_cfg.get("min_feedbacks_for_recalibration", 5)

    await init_db()

    async with session_scope() as session:
        # Récupère toutes les opportunités avec décision Go/No-Go
        stmt = (
            select(Opportunity)
            .where(Opportunity.client_decision.in_(["GO", "GO_SUBMITTED", "NO_GO"]))
            .where(Opportunity.score_breakdown.isnot(None))
        )
        result = await session.execute(stmt)
        opps = result.scalars().all()

        n = len(opps)
        if n < min_feedbacks:
            logger.warning(
                "not_enough_feedback",
                got=n,
                needed=min_feedbacks,
                msg="Skipping recalibration",
            )
            print(f"⚠️  Seulement {n}/{min_feedbacks} feedbacks. Recalibration skipped.")
            return

        # Construire matrice X (sous-scores normalisés [0..1]) et y (1 si GO, 0 si NO_GO)
        X, y = [], []
        for opp in opps:
            br = opp.score_breakdown or {}
            row = []
            for crit in CRITERIA:
                # On a stocké le sous-score pondéré → on le normalise par le poids initial
                weight = profile["scoring_weights"].get(crit, 1) or 1
                contrib = br.get(crit, 0.0)
                # Sous-score "brut" sur 100
                raw_score = (contrib / weight) * 100 if weight else 0
                row.append(raw_score)
            X.append(row)
            y.append(1 if opp.client_decision in ("GO", "GO_SUBMITTED") else 0)

        X = np.array(X, dtype=float)
        y = np.array(y, dtype=int)

        if len(set(y)) < 2:
            logger.warning(
                "single_class_only",
                msg="Need both GO and NO_GO examples to recalibrate",
            )
            print("⚠️  Une seule classe présente (que des Go ou que des No-Go). Skip.")
            return

        # Régression logistique
        clf = LogisticRegression(
            penalty="l2",
            C=1.0,
            class_weight="balanced",
            max_iter=1000,
            random_state=42,
        )
        clf.fit(X, y)
        coefs = clf.coef_[0]

        # On ne garde que les coefs positifs (un coef négatif voudrait dire que
        # le critère pousse vers No-Go, ce qui n'a pas de sens dans notre design :
        # tous nos sous-scores sont "plus = mieux"). On floor à 0 puis on
        # normalise pour sommer à 100.
        coefs_pos = np.maximum(coefs, 0.0)
        if coefs_pos.sum() == 0:
            logger.warning("all_coefs_zero — fallback to current weights")
            return
        new_weights = coefs_pos / coefs_pos.sum() * 100

        # Sauvegarde
        new_weights_dict = {c: round(float(w), 2) for c, w in zip(CRITERIA, new_weights)}
        weights_repo = WeightsRepo(session)
        version = await weights_repo.save_new_version(
            weights=new_weights_dict,
            based_on_n_feedbacks=n,
            method="logistic_regression",
        )

        # Log lisible
        logger.info(
            "weights_recalibrated",
            version=version.version,
            n_feedbacks=n,
            accuracy=round(float(clf.score(X, y)), 3),
        )
        print(f"\n✓ Nouvelle version de poids #{version.version} (sur {n} feedbacks)")
        print(f"  Précision sur train : {round(clf.score(X, y) * 100, 1)}%")
        print("  Nouveaux poids :")
        for c, w in new_weights_dict.items():
            print(f"    {c:>26} : {w:>5.2f}")


if __name__ == "__main__":
    asyncio.run(main())
