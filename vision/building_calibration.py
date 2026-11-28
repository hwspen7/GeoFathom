"""Validation-only binary probability calibration with bounded pixel statistics.

Temperature scales log odds, not geometry. Reports keep the raw classification
operating point unchanged. Neither pixel confidence nor calibration establishes
the probability that an entire building is correctly mapped.
"""
import numpy as np
from scipy.special import expit

TEMPERATURES = (.5, .67, .8, 1., 1.25, 1.5, 2., 3., 4.)


def log_odds(probability):
    p = np.asarray(probability, dtype=np.float64)
    if not np.isfinite(p).all() or np.any((p < 0) | (p > 1)):
        raise ValueError("Expected finite building probabilities in [0,1].")
    p = np.clip(p, 1e-6, 1.-1e-6)
    return np.log(p)-np.log1p(-p)


class TemperatureFit:
    """Stream exact validation NLL on a predeclared finite temperature grid."""
    def __init__(self):
        self.losses = np.zeros(len(TEMPERATURES), np.float64)
        self.count = 0
        self.positive = 0

    def update(self, p, labels):
        logits = log_odds(p)
        y = np.asarray(labels)
        if y.shape != logits.shape or not np.isin(y, [0, 1]).all():
            raise ValueError("Binary calibration labels must match the prediction array.")
        for i, temperature in enumerate(TEMPERATURES):
            scaled = logits / temperature
            self.losses[i] += np.logaddexp(0., np.where(y == 1, -scaled, scaled)).sum()
        self.count += int(y.size)
        self.positive += int(y.sum())

    def result(self):
        if not 0 < self.positive < self.count:
            return {"temperature": 1., "fitted": False, "validation_pixels": self.count,
                    "reason": "Validation requires both building and background pixels."}
        i = min(range(len(TEMPERATURES)), key=lambda k: (self.losses[k], abs(TEMPERATURES[k]-1.)))
        baseline = TEMPERATURES.index(1.)
        return {"temperature": TEMPERATURES[i], "fitted": True, "validation_pixels": self.count,
                "raw_nll": float(self.losses[baseline]/self.count),
                "selected_nll": float(self.losses[i]/self.count),
                "candidates": [{"temperature": t, "nll": float(loss/self.count)}
                               for t, loss in zip(TEMPERATURES, self.losses)]}


class ProbabilityDiagnostics:
    """Pool reliability-bin counts, Brier score, NLL and selective error."""
    def __init__(self):
        self.counts = np.zeros(10, np.int64)
        self.predicted = np.zeros(10, np.float64)
        self.observed = np.zeros(10, np.float64)
        self.brier = self.nll = 0.
        self.coverage = np.zeros((4, 2), np.int64)

    def update(self, probabilities, labels, temperature=1.):
        logits = log_odds(probabilities)/temperature
        y = np.asarray(labels)
        if y.shape != logits.shape or not np.isin(y, [0, 1]).all():
            raise ValueError("Binary diagnostic labels must match the prediction array.")
        p = expit(logits)
        bins = np.minimum((p*10).astype(np.int64), 9).ravel()
        self.counts += np.bincount(bins, minlength=10)
        self.predicted += np.bincount(bins, weights=p.ravel(), minlength=10)
        self.observed += np.bincount(bins, weights=y.ravel(), minlength=10)
        self.brier += float(np.square(p-y).sum())
        self.nll += float(np.logaddexp(0., np.where(y == 1, -logits, logits)).sum())
        confidence = np.maximum(p, 1-p)
        incorrect = (p >= .5) != y
        for i, threshold in enumerate((.5, .7, .8, .9)):
            accepted = confidence >= threshold
            self.coverage[i] += [int(accepted.sum()), int((accepted & incorrect).sum())]

    def result(self):
        n = int(self.counts.sum())
        return {"pixels": n, "brier_score": self.brier/n if n else None,
                "negative_log_likelihood": self.nll/n if n else None,
                "pooled_ece": float(np.abs(self.predicted-self.observed).sum()/n) if n else None,
                "bins": [{"lower": i/10, "upper": (i+1)/10, "pixels": int(c),
                          "mean_probability": float(self.predicted[i]/c) if c else None,
                          "observed_frequency": float(self.observed[i]/c) if c else None}
                         for i, c in enumerate(self.counts)],
                "selective_error": [{"confidence_threshold": t, "accepted_pixels": int(c),
                                     "coverage": int(c)/n if n else None,
                                     "error_rate": int(e)/int(c) if c else None}
                                    for t, (c, e) in zip((.5, .7, .8, .9), self.coverage)]}
