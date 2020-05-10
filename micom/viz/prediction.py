"""Visualization for phenotype prediction."""

from datetime import datetime
from micom.viz import Visualization
from micom.logger import logger
import json
import numpy as np
import pandas as pd
from pandas.api.types import is_numeric_dtype
from sklearn.model_selection import (
    cross_val_predict,
    cross_val_score,
    LeaveOneOut,
)
from sklearn.linear_model import (
    LogisticRegressionCV,
    LassoCV,
    LogisticRegression,
    Lasso,
)
from sklearn.preprocessing import StandardScaler


def plot_fit(
    exchanges,
    phenotype,
    variable_type="binary",
    variable_name="phenotype",
    out_folder="fit_%s" % datetime.now().strftime("%Y%m%d"),
    flux_type="production",
    min_coef=0.01,
):
    """Test for differential metabolite production.

    This will fit the `phenotype` response using L1-regularized linear models
    with log-fluxes as features. Will use LASSO regression for a continuous
    response and L1-regularized Logistic regression for a binary response.

    Parameters
    ----------
    exchanges : pandas.DataFrame
        The exchanges returned by the `grow` workflow.
    phenotype : pandas.Series
        The data to be fitted. Its index must correspond to `sample_id` in
        `exchanges`.
    variable_type : str of ["binary", "continuous"]
        The type of the variable.
    variable_name : str
        A short description of the phenotype for instance "disease_status".
    out_folder : str
        The folder where the visualization will be saved.
    flux_type : str of ["import", "production"]
        Whether to fit using import or production fluxes.
    min_coef : float in [0.0, Inf]
        Only report coefficient that are at least that large.

    Returns
    -------
    Visualization
        A MICOM visualization. Can be served with `viz.serve`.

    """
    if flux_type == "import":
        exchanges = exchanges[
            (exchanges.taxon == "medium") & (exchanges.direction == "import")
        ]
        exchanges["flux"] = exchanges.flux.abs()
    else:
        exchanges = exchanges[
            (exchanges.taxon != "medium") & (exchanges.direction == "export")
        ]
        exchanges = (
            exchanges.groupby(["reaction", "metabolite", "sample_id"])
            .apply(
                lambda df: pd.Series(
                    {"flux": sum(df.abundance * df.flux.abs())}
                )
            )
            .reset_index()
        )
    exchanges.loc[exchanges.flux < 1e-6, "flux"] = 1e-6
    if variable_type == "binary" and phenotype.nunique() != 2:
        raise ValueError(
            "Binary variables must have exactly two unique values, yours "
            "has: %s." % ", ".join(phenotype.unique())
        )
    elif variable_type == "continuous" and not is_numeric_dtype(phenotype):
        raise ValueError(
            "Continuous variables must have a numeric type, but yours is"
            " of type `%s`." % phenotype.dtype
        )
    elif variable_type not in ["binary", "continuous"]:
        raise ValueError(
            "Unsupported variable type. Must be either `binary` or "
            "`continuous`."
        )

    fluxes = exchanges.pivot_table(
        index="sample_id", columns="metabolite", values="flux", fill_value=1e-6
    )
    fluxes = fluxes.applymap(np.log)
    meta = phenotype[fluxes.index]
    stds = fluxes.std(axis=1)
    bad = stds < 1e-6
    if bad.any():
        logger.warning("Removing %d fluxes due to zero variance." % bad.sum())
        fluxes = fluxes.loc[:, ~bad]
    scaled = StandardScaler().fit_transform(fluxes)
    if variable_type == "binary":
        model = LogisticRegressionCV(
            penalty="l1",
            scoring="accuracy",
            solver="liblinear",
            cv=2,
            Cs=np.power(10.0, np.arange(-6, 6, 0.5)),
            max_iter=10000,
        )
        fit = model.fit(scaled, meta)
        model = LogisticRegression(
            penalty="l1", solver="liblinear", C=fit.C_[0], max_iter=10000,
        )
        fit = model.fit(scaled, meta)
        score = cross_val_score(model, X=scaled, y=meta, cv=LeaveOneOut())
        coefs = pd.DataFrame(
            {"coef": fit.coef_[0, :], "metabolite": fluxes.columns}
        )
    else:
        model = LassoCV(cv=2, max_iter=10000)
        fit = model.fit(scaled, meta)
        model = Lasso(alpha=fit.alpha_, max_iter=10000)
        fit = model.fit(scaled, meta)
        score = cross_val_score(model, X=scaled, y=meta, cv=3)
        coefs = pd.DataFrame({"coef": fit.coef_, "metabolite": fluxes.columns})
    score = [np.mean(score), np.std(score)]
    score.append(model.score(scaled, meta))

    if all(coefs.coef.abs() < min_coef):
        raise RuntimeError(
            "Unfortunately no metabolite flux was predictive for the "
            "chosen phenotype and a cutoff of %g :(" % min_coef
        )

    data = {"fluxes": exchanges, "coefficients": coefs}
    coefs = coefs[coefs.coef.abs() >= min_coef].sort_values(by="coef")
    predicted = cross_val_predict(model, scaled, meta, cv=LeaveOneOut())
    fitted = pd.DataFrame(
        {"real": meta, "predicted": predicted}, index=meta.index
    )

    exchanges = exchanges.loc[
        exchanges.metabolite.isin(coefs.metabolite.values)
    ]
    exchanges["meta"] = meta[exchanges.sample_id].values
    var_type = "nominal" if variable_type == "binary" else "quantitative"
    viz = Visualization(out_folder, data, "tests.html")

    viz.save(
        fitted=fitted.to_json(orient="records"),
        coefs=coefs.to_json(orient="records"),
        exchanges=exchanges.to_json(orient="records"),
        metabolites=json.dumps(coefs.metabolite.tolist()),
        variable=variable_name,
        type=var_type,
        score=score,
        width=400,
        height=300,
        cheight=2 * coefs.shape[0],
        cwidth=8 * coefs.shape[0],
    )

    return viz
