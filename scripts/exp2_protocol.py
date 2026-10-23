#!/usr/bin/env python3
"""Experiment 2 — protocol outline.

Question: does cross-domain coupling carry information that a one-directional
chain does not?

Fit the Track B intervention outcomes under three coupling structures, on the
fine-tuning subset only, and score them on the validation subset:

    primary      only the domains an intervention directly forces
    sequential   adds thermal -> air quality and thermal -> energy
    full         adds vegetation -> air quality and energy -> thermal

Report, per climate × pathway cell, the IQR-normalised error of each regime and
the reduction of full over sequential; test it with a paired cluster bootstrap
over publications, Holm-corrected across the grid.

This file states the design. Stages are named, not implemented.
"""

REGIMES = ("primary", "sequential", "full")

# load -> verify split -> build (climate, intervention, reachable domains)
#   -> fit fine-tuning -> score validation -> group into cells -> compare
