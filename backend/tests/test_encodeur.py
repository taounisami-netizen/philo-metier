"""Encodeur ONNX : testé avec un mini-modèle construit ici (pas besoin de télécharger le vrai)."""

import numpy as np
import pytest

from app.encodeur import Encodeur, ModeleIntrouvable, moyenne_normalisee

onnx = pytest.importorskip("onnx")
sentencepiece = pytest.importorskip("sentencepiece")

MOTS = ["le", "sage", "doute", "agit"]
# Numéros dans le modèle : 0 <s>, 1 remplissage, 2 </s>, 3 inconnu, puis les mots à partir de 4.
NUMERO = {m: 4 + i for i, m in enumerate(MOTS)}


@pytest.fixture
def dossier_modele(tmp_path):
    # Découpeur SentencePiece minimal : un mot = un morceau (comme le vrai, numérotés à partir de 0 = inconnu).
    from sentencepiece import sentencepiece_model_pb2 as pb

    sp = pb.ModelProto()
    sp.trainer_spec.model_type = pb.TrainerSpec.UNIGRAM
    for morceau, genre in [("<unk>", pb.ModelProto.SentencePiece.UNKNOWN),
                           ("<s>", pb.ModelProto.SentencePiece.CONTROL),
                           ("</s>", pb.ModelProto.SentencePiece.CONTROL)]:
        p = sp.pieces.add(); p.piece = morceau; p.type = genre
    for m in MOTS:
        p = sp.pieces.add(); p.piece = "\u2581" + m; p.score = -1.0
    sp.normalizer_spec.add_dummy_prefix = True
    sp.normalizer_spec.remove_extra_whitespaces = True
    sp.normalizer_spec.escape_whitespaces = True
    (tmp_path / "sentencepiece.bpe.model").write_bytes(sp.SerializeToString())

    # Modèle : chaque jeton reçoit le vecteur de sa ligne dans la matrice E (comme une couche d'embeddings).
    from onnx import TensorProto, helper, numpy_helper

    E = np.random.default_rng(0).normal(size=(4 + len(MOTS), 4)).astype(np.float32)
    graphe = helper.make_graph(
        [helper.make_node("Gather", ["E", "input_ids"], ["last_hidden_state"])],
        "mini",
        [helper.make_tensor_value_info("input_ids", TensorProto.INT64, ["n", "L"]),
         helper.make_tensor_value_info("attention_mask", TensorProto.INT64, ["n", "L"])],
        [helper.make_tensor_value_info("last_hidden_state", TensorProto.FLOAT, ["n", "L", 4])],
        initializer=[numpy_helper.from_array(E, "E")],
    )
    modele = helper.make_model(graphe, opset_imports=[helper.make_opsetid("", 13)])
    modele.ir_version = 8
    onnx.save(modele, str(tmp_path / "model_quantized.onnx"))
    return tmp_path, E


def attendu(E, mots):
    # Comme sentence-transformers : la moyenne inclut <s> (0) et </s> (2).
    v = E[[0, *(NUMERO[m] for m in mots), 2]].mean(axis=0)
    return v / np.linalg.norm(v)


def test_moyenne_ignore_le_remplissage():
    etats = np.array([[[1.0, 0.0], [0.0, 1.0], [100.0, 100.0]]])
    masque = np.array([[1, 1, 0]])
    np.testing.assert_allclose(moyenne_normalisee(etats, masque), [[2 ** -0.5, 2 ** -0.5]], atol=1e-6)


def test_jetons_decales_et_encadres(dossier_modele):
    dossier, _ = dossier_modele
    enc = Encodeur(dossier, threads=1)
    assert enc.jetons("le sage") == [0, NUMERO["le"], NUMERO["sage"], 2]
    assert enc.jetons("zzz")[1:-1] == [3]  # mot inconnu → 3


def test_jetons_tronques_a_512(dossier_modele):
    dossier, _ = dossier_modele
    enc = Encodeur(dossier, threads=1)
    j = enc.jetons("le " * 1000)
    assert len(j) == 512 and j[0] == 0 and j[-1] == 2


def test_encodeur_moyenne_normalisee_et_ordre_conserve(dossier_modele):
    dossier, E = dossier_modele
    enc = Encodeur(dossier, threads=1)
    # Textes de longueurs différentes dans le même lot : le plus court est complété par du remplissage.
    v = enc.encoder(["le sage doute agit", "sage", "le doute"])
    assert v.shape == (3, 4)
    np.testing.assert_allclose(v[0], attendu(E, ["le", "sage", "doute", "agit"]), atol=1e-5)
    np.testing.assert_allclose(v[1], attendu(E, ["sage"]), atol=1e-5)
    np.testing.assert_allclose(v[2], attendu(E, ["le", "doute"]), atol=1e-5)
    np.testing.assert_allclose(np.linalg.norm(v, axis=1), 1, atol=1e-5)


def test_encodeur_petits_lots_meme_resultat(dossier_modele):
    dossier, _ = dossier_modele
    enc = Encodeur(dossier, threads=1)
    textes = ["le sage", "doute", "le sage doute agit", "agit le"]
    np.testing.assert_allclose(enc.encoder(textes, taille_lot=1), enc.encoder(textes, taille_lot=16), atol=1e-6)


def test_modele_absent_message_clair(tmp_path):
    with pytest.raises(ModeleIntrouvable, match="--telecharger"):
        Encodeur(tmp_path)
