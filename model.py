"""
model.py — Treinamento, avaliação e interpretação do modelo preditivo.

Pipeline:
  1. Carrega features.parquet (gerado por features.py)
  2. Treina XGBoost com validação estratificada
  3. Avalia com AUC, F1, precision/recall
  4. Gera gráficos de SHAP e confusion matrix
  5. Salva relatório em outputs/model_report.txt

O XGBoost foi escolhido por:
  - Lidar bem com dados tabulares mistos e ausentes
  - Fornecer importância de features nativamente
  - Ser compatível com SHAP para interpretabilidade
"""
import polars as pl
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import seaborn as sns
import shap
from sklearn.model_selection import StratifiedKFold, cross_validate
from sklearn.metrics import (
    classification_report, confusion_matrix,
    roc_auc_score, roc_curve, f1_score
)
from xgboost import XGBClassifier

from config import (
    OUTPUT_DIR, PLOT_DPI, PLOT_STYLE,
    TEST_SIZE, RANDOM_STATE, N_ESTIMATORS, MAX_DEPTH, LEARNING_RATE, TOP_N_SHAP
)

plt.style.use(PLOT_STYLE)


def run_model(features_path=None) -> dict:
    """
    Carrega features, treina modelo e gera todos os artefatos de avaliação.
    Retorna dict com métricas principais.
    """
    path = features_path or (OUTPUT_DIR / "features.parquet")
    df = pl.read_parquet(path)

    X, y, feature_names = _prepare_data(df)
    print(f"[model] {X.shape[0]:,} amostras × {X.shape[1]} features | "
          f"classe positiva: {y.mean():.1%}")

    model, metrics = _train_evaluate(X, y, feature_names)
    _plot_roc(metrics["fpr"], metrics["tpr"], metrics["auc"])
    _plot_confusion(metrics["y_test"], metrics["y_pred"])
    _plot_shap(model, X, feature_names)
    _save_report(metrics, feature_names)

    return metrics


# ── Privados ──────────────────────────────────────────────────────────────────

def _prepare_data(df: pl.DataFrame):
    """Separa X e y; remove colunas de metadados e leaky (label components)."""
    drop = {"message_id", "list", "from", "date",
            "accepted", "accept_score",
            "has_accept_trailer", "has_reply"}  # leaky!

    feature_cols = [c for c in df.columns if c not in drop
                    and df[c].dtype not in {pl.Utf8, pl.Boolean}]

    X = df.select(feature_cols).to_numpy().astype(np.float32)
    y = df["accepted"].cast(pl.Int8).to_numpy()

    # Substitui NaN por -1 (XGBoost lida nativamente, mas sklearn metrics não)
    X = np.nan_to_num(X, nan=-1.0)
    return X, y, feature_cols


def _train_evaluate(X: np.ndarray, y: np.ndarray, feature_names: list) -> tuple:
    """
    Treina com cross-validation estratificado 5-fold para resultados robustos.
    Treina modelo final no dataset completo para SHAP e artefatos.
    """
    model = XGBClassifier(
        n_estimators=N_ESTIMATORS,
        max_depth=MAX_DEPTH,
        learning_rate=LEARNING_RATE,
        subsample=0.8,
        colsample_bytree=0.8,
        eval_metric="logloss",
        random_state=RANDOM_STATE,
        n_jobs=-1,
    )

    # Cross-validation (5-fold estratificado)
    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=RANDOM_STATE)
    cv_results = cross_validate(
        model, X, y, cv=cv,
        scoring=["roc_auc", "f1", "precision", "recall"],
        return_train_score=False,
    )

    # Modelo final (treino completo) — para SHAP e gráficos
    model.fit(X, y)
    y_pred = model.predict(X)
    y_prob = model.predict_proba(X)[:, 1]
    fpr, tpr, _ = roc_curve(y, y_prob)

    # Split simples para confusion matrix (mais ilustrativo para o artigo)
    split = int(len(X) * (1 - TEST_SIZE))
    y_test, y_pred_test = y[split:], model.predict(X[split:])

    metrics = {
        "cv_auc":       cv_results["test_roc_auc"],
        "cv_f1":        cv_results["test_f1"],
        "cv_precision": cv_results["test_precision"],
        "cv_recall":    cv_results["test_recall"],
        "auc":          roc_auc_score(y, y_prob),
        "fpr": fpr, "tpr": tpr,
        "y_test": y_test, "y_pred": y_pred_test,
        "report": classification_report(y_test, y_pred_test,
                                        target_names=["Rejeitado", "Aceito"]),
    }

    print(f"[model] AUC (CV 5-fold): {metrics['cv_auc'].mean():.4f} "
          f"± {metrics['cv_auc'].std():.4f}")
    print(f"[model] F1  (CV 5-fold): {metrics['cv_f1'].mean():.4f} "
          f"± {metrics['cv_f1'].std():.4f}")

    return model, metrics


def _plot_roc(fpr, tpr, auc: float) -> None:
    fig, ax = plt.subplots(figsize=(5, 5))
    ax.plot(fpr, tpr, lw=2, label=f"AUC = {auc:.4f}")
    ax.plot([0, 1], [0, 1], "k--", lw=1, alpha=0.5)
    ax.set_xlabel("Taxa de falso positivo")
    ax.set_ylabel("Taxa de verdadeiro positivo")
    ax.set_title("Curva ROC — Predição de aceitação de patches", pad=10)
    ax.legend(loc="lower right")
    _save(fig, "model_roc_curve")


def _plot_confusion(y_true, y_pred) -> None:
    cm = confusion_matrix(y_true, y_pred)
    labels = ["Rejeitado", "Aceito"]
    fig, ax = plt.subplots(figsize=(5, 4))
    sns.heatmap(cm, annot=True, fmt="d", cmap="Blues",
                xticklabels=labels, yticklabels=labels, ax=ax)
    ax.set_title("Matriz de confusão", pad=10)
    ax.set_xlabel("Predito"); ax.set_ylabel("Real")
    _save(fig, "model_confusion_matrix")


def _plot_shap(model, X: np.ndarray, feature_names: list) -> None:
    """SHAP summary plot — interpreta o modelo de forma global."""
    explainer = shap.TreeExplainer(model)
    # Usa amostra para velocidade (até 5k linhas)
    idx = np.random.default_rng(RANDOM_STATE).choice(
        len(X), size=min(5_000, len(X)), replace=False
    )
    shap_values = explainer.shap_values(X[idx])

    fig, ax = plt.subplots(figsize=(8, 6))
    shap.summary_plot(
        shap_values, X[idx],
        feature_names=feature_names,
        max_display=TOP_N_SHAP,
        plot_type="bar",
        show=False,
        color=plt.cm.Blues(0.6),
    )
    plt.title("Importância das features (SHAP)", pad=10, fontsize=13)
    _save(plt.gcf(), "model_shap_importance")

    # SHAP beeswarm (mais rico — mostra direção do efeito)
    shap.summary_plot(
        shap_values, X[idx],
        feature_names=feature_names,
        max_display=TOP_N_SHAP,
        show=False,
    )
    plt.title("Efeito das features (SHAP beeswarm)", pad=10, fontsize=13)
    _save(plt.gcf(), "model_shap_beeswarm")


def _save_report(metrics: dict, feature_names: list) -> None:
    """Salva relatório textual para o artigo."""
    lines = [
        "=" * 55,
        "  RELATÓRIO DO MODELO — Predição de aceitação de patches",
        "=" * 55,
        "",
        "Cross-validation 5-fold estratificado:",
        f"  AUC       : {metrics['cv_auc'].mean():.4f} ± {metrics['cv_auc'].std():.4f}",
        f"  F1        : {metrics['cv_f1'].mean():.4f} ± {metrics['cv_f1'].std():.4f}",
        f"  Precision : {metrics['cv_precision'].mean():.4f} ± {metrics['cv_precision'].std():.4f}",
        f"  Recall    : {metrics['cv_recall'].mean():.4f} ± {metrics['cv_recall'].std():.4f}",
        "",
        "Classification report (hold-out 20%):",
        metrics["report"],
        "",
        f"Features utilizadas ({len(feature_names)}):",
        *[f"  {f}" for f in feature_names],
        "",
        "Modelo: XGBoost",
        f"  n_estimators={N_ESTIMATORS}, max_depth={MAX_DEPTH}, lr={LEARNING_RATE}",
    ]
    path = OUTPUT_DIR / "model_report.txt"
    path.write_text("\n".join(lines))
    print(f"[model] Relatório salvo em {path.name}")


def _save(fig, name: str) -> None:
    path = OUTPUT_DIR / f"{name}.png"
    fig.tight_layout()
    fig.savefig(path, dpi=PLOT_DPI, bbox_inches="tight")
    plt.close(fig)
    print(f"  → {path.name}")
