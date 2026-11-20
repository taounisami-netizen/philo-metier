"""Encodeur de textes léger : multilingual-e5-small au format ONNX, quantifié en int8.

Pourquoi pas sentence-transformers ? Il entraîne PyTorch (~1 Go en mémoire), trop lourd
pour un hébergement gratuit (512 Mo). Ici, le même modèle tourne avec onnxruntime
(~145 Mo en mémoire), et le texte est découpé en jetons par SentencePiece, le découpeur
d'origine du modèle (~55 Mo, contre ~280 Mo pour tokenizer.json et la bibliothèque tokenizers).

Le calcul reproduit celui de sentence-transformers pour e5 :
  1. découper le texte en jetons : <s> + morceaux de mots + </s>, 512 jetons au plus ;
  2. le modèle donne un vecteur h_t (d = 384) pour chaque jeton t ;
  3. moyenne des vecteurs des vrais jetons (pas du remplissage) : v = Σ m_t·h_t / Σ m_t ;
  4. normalisation : v / ‖v‖, pour que le produit scalaire soit le cosinus.

Usage (depuis backend/) :
    python -m app.encodeur --telecharger    → télécharge le modèle dans modele/ (~125 Mo)
"""

import os
import sys
import urllib.request
from pathlib import Path

import numpy as np

DEPOT = "Xenova/multilingual-e5-small"
NOM_MODELE = f"{DEPOT} (onnx int8)"  # écrit dans corpus/index.json
FICHIERS = {  # nom local → adresse sur Hugging Face
    "model_quantized.onnx": f"{DEPOT}/resolve/main/onnx/model_quantized.onnx",
    "sentencepiece.bpe.model": "intfloat/multilingual-e5-small/resolve/main/sentencepiece.bpe.model",
}
DOSSIER_MODELE = Path(os.environ.get("MODELE_DIR", Path(__file__).parent.parent / "modele"))
LONGUEUR_MAX = 512
# Numéros des jetons spéciaux du modèle (convention XLM-RoBERTa / fairseq).
DEBUT, REMPLISSAGE, FIN, INCONNU = 0, 1, 2, 3


class ModeleIntrouvable(RuntimeError):
    pass


def moyenne_normalisee(etats: np.ndarray, masque: np.ndarray) -> np.ndarray:
    """etats : (n, L, d), masque : (n, L) de 0/1 → (n, d), chaque ligne de norme 1."""
    m = masque[:, :, None].astype(np.float32)
    somme = (etats * m).sum(axis=1)
    moyenne = somme / np.clip(m.sum(axis=1), 1e-9, None)
    return moyenne / np.clip(np.linalg.norm(moyenne, axis=1, keepdims=True), 1e-12, None)


class Encodeur:
    def __init__(self, dossier: Path = DOSSIER_MODELE, threads: int | None = None):
        manquants = [nom for nom in FICHIERS if not (dossier / nom).exists()]
        if manquants:
            raise ModeleIntrouvable(
                f"Modèle absent de {dossier} ({', '.join(manquants)}). "
                "Lance : python -m app.encodeur --telecharger"
            )
        import onnxruntime as ort  # imports lents : seulement si on encode vraiment
        import sentencepiece

        self.decoupeur = sentencepiece.SentencePieceProcessor(model_file=str(dossier / "sentencepiece.bpe.model"))

        options = ort.SessionOptions()
        threads = threads or int(os.environ.get("ONNX_THREADS", "0"))
        if threads:  # 0 = laisser onnxruntime choisir (tous les cœurs)
            options.intra_op_num_threads = threads
            options.inter_op_num_threads = 1
        options.enable_cpu_mem_arena = False  # moins de mémoire réservée d'avance (serveur à 512 Mo)
        self.session = ort.InferenceSession(
            str(dossier / "model_quantized.onnx"), options, providers=["CPUExecutionProvider"]
        )
        self.entrees = {e.name for e in self.session.get_inputs()}

    def jetons(self, texte: str) -> list[int]:
        """Numéros des jetons du texte, tels que le modèle les attend.

        SentencePiece numérote ses morceaux à partir de 0 (0 = inconnu). Le modèle, lui, a
        réservé 0 à 3 pour <s>, <remplissage>, </s>, <inconnu> : on décale donc de 1.
        """
        morceaux = [i + 1 if i else INCONNU for i in self.decoupeur.encode(texte)]
        return [DEBUT, *morceaux[: LONGUEUR_MAX - 2], FIN]

    def _lot(self, textes: list[str]) -> np.ndarray:
        sequences = [self.jetons(t) for t in textes]
        longueur = max(len(s) for s in sequences)
        ids = np.full((len(textes), longueur), REMPLISSAGE, dtype=np.int64)
        masque = np.zeros((len(textes), longueur), dtype=np.int64)
        for i, s in enumerate(sequences):
            ids[i, : len(s)] = s
            masque[i, : len(s)] = 1
        donnees = {"input_ids": ids, "attention_mask": masque}
        if "token_type_ids" in self.entrees:
            donnees["token_type_ids"] = np.zeros_like(ids)
        etats = self.session.run(None, {k: v for k, v in donnees.items() if k in self.entrees})[0]
        return moyenne_normalisee(etats, masque)

    def encoder(self, textes: list[str], taille_lot: int = 16, progression: bool = False) -> np.ndarray:
        """Matrice (n, 384) de vecteurs normalisés, dans l'ordre des textes."""
        if not textes:
            return np.zeros((0, 384), dtype=np.float32)
        # On regroupe les textes de longueur voisine : moins de remplissage, calcul plus rapide.
        ordre = sorted(range(len(textes)), key=lambda i: len(textes[i]))
        resultat: list[np.ndarray | None] = [None] * len(textes)
        for debut in range(0, len(ordre), taille_lot):
            indices = ordre[debut : debut + taille_lot]
            for i, v in zip(indices, self._lot([textes[i] for i in indices])):
                resultat[i] = v
            if progression:
                print(f"\r  {min(debut + taille_lot, len(ordre))}/{len(ordre)}", end="", flush=True)
        if progression:
            print()
        return np.asarray(resultat, dtype=np.float32)


def telecharger(dossier: Path = DOSSIER_MODELE) -> None:
    dossier.mkdir(parents=True, exist_ok=True)
    for nom, chemin in FICHIERS.items():
        cible = dossier / nom
        if cible.exists():
            print(f"{nom} : déjà là")
            continue
        url = f"https://huggingface.co/{chemin}"
        print(f"{nom} : téléchargement depuis {url}")
        temporaire = cible.with_suffix(cible.suffix + ".part")
        urllib.request.urlretrieve(url, temporaire)
        temporaire.rename(cible)
        print(f"  {cible.stat().st_size / 1e6:.0f} Mo")


if __name__ == "__main__":
    if "--telecharger" in sys.argv:
        telecharger()
    else:
        print(__doc__)
